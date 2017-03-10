from netmiko import ConnectHandler
from wylog import log, logging
from datetime import datetime
from time import sleep
from util import is_ip

import re, hashlib, util, os, cli
import config


class interface():
    '''Generic network device interface'''
    def __init__(self, **kwargs):
        
        self.interface_description = kwargs.pop('interface_description', None)
        self.tunnel_destination_ip = kwargs.pop('tunnel_destination_ip', None)
        self.interface_subnet = kwargs.pop('interface_subnet', None)
        self.interface_status = kwargs.pop('interface_status', None)
        self.remote_interface = kwargs.pop('remote_interface', None)
        self.interface_number = kwargs.pop('interface_number', None)
        self.interface_name = kwargs.pop('interface_name', None)
        self.interface_type = kwargs.pop('interface_type', None)
        self.tunnel_status = kwargs.pop('tunnel_status', None)
        self.raw_interface = kwargs.pop('raw_interface', None)
        self.interface_ip = kwargs.pop('interface_ip', None)
        self.interface_id = kwargs.pop('interface_id', None)
        self.virtual_ip = kwargs.pop('virtual_ip', None)
        self.device_id = kwargs.pop('device_id', None)
        
        # Mutable Arguments
        self.mac_address_table = []
        self.neighbors = []
        

    
    def __str__(self):
            
        output = []
        for var, value in vars(self).items(): output.append(var + ': ' + str(value))
        return '\n'.join(str(x) for x in sorted(output))
    


class network_device():
    '''Generic network device'''
    def __init__(self, **kwargs):
        # Immutable arguments
        self.raw_mac_address_table = kwargs.pop('raw_mac_address_table', None)
        self.netmiko_platform = kwargs.pop('netmiko_platform', None)
        self.system_platform = kwargs.pop('system_platform', None)
        self.process_name = kwargs.pop('process_name', None)
        self.neighbor_id = kwargs.pop('neighbor_id', None)        
        self.device_name = kwargs.pop('device_name', None)
        self.connection = kwargs.pop('connection', None)
        self.AD_enabled = kwargs.pop('AD_enabled', None)
        self.device_id = kwargs.pop('device_id', None)
        self.software = kwargs.pop('software', None)
        self.raw_cdp = kwargs.pop('raw_cdp', None)
        self.config = kwargs.pop('config', None)
        self.TCP_22 = kwargs.pop('TCP_22', None)
        self.TCP_23 = kwargs.pop('TCP_23', None)
        self.ip = kwargs.pop('ip', None)
        
        # Mutable arguments
        self.credentials = kwargs.pop('credentials', {})
        self.mac_address_table = []
        self.serial_numbers = []
        self.interfaces = []
        self.neighbors = []
        self.other_ips = []
        
        # Other Args
        self.processing_error = False
        self.failed = False
        self.error_log = ''
        
        
    def __str__(self):
        try: serial= ', '.join([x + ': ' + y  for x, y in self.first_serial().items()])
        except: serial= 'None'
        
        return '\n'.join([
            'Device Name:       ' + str(self.device_name),
            'Unique Name:       ' + str(self.unique_name()),
            'Management IP:     ' + str(self.ip),
            'First Serial:      ' + serial,
            'Serial Count:      ' + str(len(self.serial_numbers)),
            'Dynamic MAC Count: ' + str(len(self.mac_address_table)),
            'Interface Count:   ' + str(len(self.interfaces)),
            'Neighbor Count:    ' + str(len(self.all_neighbors())),
            'Config Size:       ' + str(len(self.config))
            ])
    
    
    
    def alert(self, msg, proc, failed=False, v=logging.A, ip=None):
        '''Populates the failed messages variable for the device'''
        if failed: self.failed = failed
        self.error = True
        self.error_log += '{} - IP [{}]: {} | '.format(proc, ip, msg)
        
        log(msg=msg, proc=proc, v=v, ip=ip)
    
    
    def add_ip(self, ip):
        """Adds an IP address to the list of other IPs
        
        Args:
            ip (string): An IP address
        """
        if not ip in self.other_ips:
            self.other_ips.append(ip)
 
 
    def save_config(self):
        proc = 'base_device.save_config'
        log('Saving config.', proc=proc, v=logging.I)
        
        path = config.device_path() + self.unique_name() + '/' 
        filename = datetime.now().strftime(config.file_time()) + '.cfg'
        
        if not os.path.exists(path):
            os.makedirs(path)
        
        with open(path + filename, 'a') as outfile:       
            outfile.write('\n'.join([
                datetime.now().strftime(config.file_time()),
                self.config,
                '\n']))
                
        log('Saved config.', proc=proc, v=logging.N)
    
    
    def all_neighbors(self):
        _list = []
        for n in self.neighbors:
            _list.append(n)
            
        for i in self.interfaces:
            for n in i.neighbors:
                _list.append(n)
                
        return _list
    
    
    def neighbor_table(self, sh_src=True, sh_name=True, sh_ip=True, sh_platform=True):
        """Returns a formatted table of neighbors.
        
        Optional Args:
            sh_src (Boolean): When true, show the source interface for each entry
            sh_name (Boolean): When true, show the hostname for each entry
            sh_ip (Boolean): When true, show the IP address for each entry
            sh_platform (Boolean): When true, show the system platform for each entry
            
        """ 
        
        output = ''
        
        entries = []
        
        # Add the table header
        entry = ''
        if sh_name: entry += '     {name:^30}  '.format(name='Neighbor Name')
        if sh_src: entry += '{src:^25} '.format(src='Source Interface')
        if sh_platform: entry += '{platform:^10} '.format(platform='Platform')
        if sh_ip: entry += '{ip:^15} '.format(ip='IP')
        entries.append(entry)
        
        # Populate the table
        for n in self.all_neighbors():
            entry = '-- '
            if sh_name: entry += '{name:30.29}, '.format(name=n['device_name'])
            if sh_src: entry += '{src:25}, '.format(src=n['source_interface'])
            if sh_platform: entry += '{platform}'.format(platform=n['system_platform'])
            if sh_ip: entry += '{ip:15}, '.format(ip=str(n['ip_list']))
            entries.append(entry)
        
        entries.append('\n* Un-Matched source interface')
        output += '\n'.join(entries)
        
        return output
        
    
    def merge_interfaces(self, new_interfaces):
        """Merges a list of interfaces with the ones currently in the device.
        If the interface name matches, then the new interface will overwrite 
        any old data it has new entries for.
        
        Args:
            new_interfaces (List of interface objects): One or more interface objects
        """
        proc = 'base_device.merge_interfaces'
         
        for new_interf in new_interfaces:
            match = False
            for old_interf in self.interfaces:
                # If the new interface name matches the saved name
                if new_interf.interface_name == old_interf.interface_name:
                    match = True
                    log('Interface {} merged with old interface'.
                        format(new_interf.interface_name),
                        proc=proc,
                        v=logging.D)
                    # For each variable in the interface class, compare and overwrite new ones.
                    for key in config(new_interf).keys():
                        config(old_interf)[key] = config(new_interf)[key] 
            
            if not match: self.interfaces.append(new_interf)
    
    
    def interfaces_to_string(self):
        output = '\n----------\n'.join(str(interf) for interf in self.interfaces)           
        return output
            
    
    def get_ips(self):
        """Returns a list of IP addresses aggregated from interfaces."""
        
        # Get the IP from each interface
        output = [i.interface_ip for i in self.interfaces if is_ip(i)]
        
        # Add any other IP's it has
        output.extend(self.other_ips)
            
        return output


    def unique_name(self, name=True, serials=True):
        """Returns a unique identifier for this device"""
        
        if not (self.device_name or self.serial_numbers):
            return None
        
        output = []
        
        if name and self.device_name: output.append(self.device_name)
        
        # Make a hash of the serials        
        if serials and len(self.serial_numbers) > 0:
            h = hashlib.md5()
            for x in sorted(self.serial_numbers, key=lambda k: k['serialnum']):
                h.update(x['serialnum'].encode())
            output.append(h.hexdigest()[:5])
        
        return '_'.join(output).upper()
        
    
    def first_serial(self):
        if len(self.serial_numbers) == 0: return None
        else: return self.serial_numbers[0]['serialnum']
          
    
    def process_device(self):
        '''Main method which fully populates the network_device'''
        proc = 'base_device.process_devices'
        
        log('Processing device', proc=proc, v=logging.N)
        
        # Connect to the device
        try: result = cli.start_cli_session(handler=ConnectHandler,
                                          netmiko_platform=self.netmiko_platform,
                                          ip=self.ip,
                                          )
        except Exception as e:
            self.alert('Connection failed', proc=proc)
            raise
        
        # Error checking
        for k, v in result.items():
            assert v is not None, 'Result[\'{key}\'] is None, should have value.'.format(k)
        
        # Import results of CLI connection into device variables
        self.connection = result['connection']
        self.TCP_22 = result['TCP_22']
        self.TCP_23 = result['TCP_23']
        self.credentials = result['cred']
        
        # Functions that must work consecutively in order to proceed
        # On error, these raise an exception and fail the processing
        for fn in (
            self._enable(),
            self._get_config(),
            self._parse_hostname(),
            self._get_interfaces(),
            ):
            try:
                fn
            except Exception as e:
                self.alert(msg=fn.__name__ + ' - Error: ' + str(e),
                           proc=proc,)
                raise
        
        # These are optional, and only leave a log message when they 
        # fail (unless SUPPRESS_EXCEPTION has been set False)
        for fn in (
            self._get_serials(),
            self._get_other_ips(),
            self._get_cdp_neighbors(),
            self._get_mac_address_table(),
            self._normalize_netmasks()  # Must be after all IP polling
            ):
            try: 
                fn
            except Exception as e:
                self.alert(fn.__name__ + ' - Error: ' + str(e), proc=proc)
                if config.raise_exceptions(): raise
               
        
        log('Finished polling {}'.format(self.unique_name()), proc=proc, v=logging.H)
        self.connection.disconnect()
        self.connection = None
        return True
    
    
    
    def _get_serials(self):
        self.alert('No inherited method replaced this method.', 'base_device._get_serials')
        
    def _get_config(self):
        self.alert('No inherited method replaced this method.', 'base_device._get_config')
                
    def _parse_hostname(self):
        self.alert('No inherited method replaced this method.', 'base_device._parse_hostname')
                
    def _get_cdp_neighbors(self):
        self.alert('No inherited method replaced this method.', 'base_device._get_cdp_neighbors')
            
    def _get_interfaces(self):
        self.alert('No inherited method replaced this method.', 'base_device._get_interfaces')
            
    def _get_other_ips(self):
        self.alert('No inherited method replaced this method.', 'base_device._get_other_ips')
        
    def _get_mac_address_table(self):
        self.alert('No inherited method replaced this method.', 'base_device._get_mac_address_table')     
        
    
    def _normalize_netmasks(self):
        for i in self.interfaces:
            try: netmask = util.cidr_to_netmask(i.interface_subnet)
            except ValueError: pass
            else: i.interface_subnet = netmask
    
    
    def _normalize_mac_address(self, mac):
        return ''.join([x.upper() for x in mac if re.match(r'\w', x)])
    
      
    
    def _enable(self, attempts=3):
        '''Enter enable mode.
        
        Returns:
            Boolean: True if enable mode successful.
        '''
        proc = 'base_device._enable'
        
        for i in range(attempts):
            
            # Attempt to enter enable mode
            try: self.connection.enable()
            except Exception as e: 
                log('Enable failed on attempt %s.' % (str(i + 1)),
                    ip=self.connection.ip, proc=proc, v=logging.A, error=e)
                
                # At the final try, return the failed device.
                if i >= attempts - 1: 
                    raise ValueError('Enable failed after {} attempts'.format(str(i+1)))
                
                # Otherwise rest for one second longer each time and then try again
                sleep(i + 2)
                continue
            else: 
                log('Enable successful on attempt %s' % (str(i + 1)),
                    ip=self.connection.ip, proc=proc, v=logging.D)
                
                return True
    
    
    
    def _attempt(self,
                command,
                proc,
                fn_check,
                v=logging.C,
                attempts=3,
                alert=True,
                check_msg=None
                ):
        '''Attempts to send a command to a remote device.
        
        Args:
            command (String): The command to send
            proc (String): The calling process (for wylog purposes)
            fn_check (Lambda): A boolean function to evaluate the output
            
        Optional Args:
            v (Integer): log alert level for a failed run
            attempts (Integer): Number of times to try the command
            alert (Boolean): LIf True, log failed attempts
        
        '''
        for i in range(attempts):
            try:
                output = self.connection.send_command_expect(command)
            except Exception as e:
                if i < (attempts - 1):
                    log('Attempt: {} - Failed Command: {} - Error: {}'.format(str(i + 1),
                        command, str(e)), proc=proc, v=logging.I)
                    # Sleep for an increasing amount of time
                    sleep(i * i + 1)
                    continue
                else:
                    if alert: self.alert('Attempt Final: {} - Failed Command: {} - Error: {}'.format(str(i + 1),
                        command, str(e)), proc=proc)
                    raise ValueError('Attempt Final: {} - Failed Command: {} - Error: {}'.format(str(i + 1),
                        command, str(e)))
            else:
                # Evaluate the returned output using the passed lamda function
                if fn_check(output): 
                    log('Attempt: {} - Successful Command: {}'.format(str(i + 1), command), proc=proc, v=logging.I)
                    return output
                
                elif i < (attempts - 1):
                    log('Attempt: {} - Check Failed on Command: {}'.format(
                        str(i + 1), command), proc=proc, v=logging.I)
                    
                    # Sleep for an increasing amount of time
                    sleep(i * i + 1)
                    continue
                else:
                    if alert: self.alert('Attempt Final: {} - Check Failed on Command: {}'.format(str(i + 1),
                        command), proc=proc)
                    raise ValueError('Attempt Final: {} - Check Failed on Command: {}'.format(str(i + 1),
                        command))

    
