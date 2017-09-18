# -*- encoding: utf-8 -*-
'''
HubbleStack Nova plugin for using systemctl to verify status of a given service.

Supports both blacklisting and whitelisting patterns. Blacklisted services must
not be running. Whitelisted services must be running.

:maintainer: HubbleStack / basepi
:maturity: 2017.8.29
:platform: All
:requires: SaltStack

This audit module requires yaml data to execute. It will search the local
directory for any .yaml files, and if it finds a top-level 'systemctl' key, it will
use that data.

Sample YAML data, with inline comments:


systemctl:
  whitelist: # or blacklist
    dhcpd-disabled:  # unique ID
      data:
        CentOS Linux-7:  # osfinger grain
         tag: 'CIS-1.1.1'  # audit tag
         service: dhcpd    # mandatory field.
      description: Ensure DHCP Server is not enabled
      alert: email
      trigger: state


'''
from __future__ import absolute_import
import logging

import fnmatch
import yaml
import os
import copy
import salt.utils
import re

from distutils.version import LooseVersion

log = logging.getLogger(__name__)


def __virtual__():
    if salt.utils.is_windows():
        return False, 'This audit module only runs on linux'
    return True


def audit(data_list, tags, debug=False, **kwargs):
    '''
    Run the systemctl audits contained in the YAML files processed by __virtual__
    '''
    __data__ = {}
    for profile, data in data_list:
        _merge_yaml(__data__, data, profile)
    __tags__ = _get_tags(__data__)

    if debug:
	log.debug('systemctl audit __data__:')
        log.debug(__data__)
        log.debug('systemctl audit __tags__:')
        log.debug(__tags__)
   
    ret = {'Success': [], 'Failure': [], 'Controlled': []}
    for tag in __tags__:
        if fnmatch.fnmatch(tag, tags):
            for tag_data in __tags__[tag]:
                if 'control' in tag_data:
                    ret['Controlled'].append(tag_data)
                    continue
                name = tag_data['name']
                audittype = tag_data['type']
		disabled_states = ["disabled", "not_found", "indirect"]

                status_code, status = _systemctl(name)
                # Blacklisted service (must not be running or not found)
                if audittype == 'blacklist':
		    if status_code == "1" or status in disabled_states:
                    	ret['Success'].append(tag_data)
		    else:
			tag_data["failure_reason"] = "Service Status: " + status + ", return code: " + status_code
			ret['Failure'].append(tag_data)
                # Whitelisted pattern (must be found and running)
                elif audittype == 'whitelist':
		    if status_code == "0":
                    	ret['Success'].append(tag_data)
		    else:
			tag_data["failure_reason"] = "Service Status: " + status + ", return code: " + status_code
			ret['Failure'].append(tag_data)

    return ret


def _merge_yaml(ret, data, profile=None):
    '''
    Merge two yaml dicts together at the systemctl:blacklist and systemctl:whitelist level
    '''
    if 'systemctl' not in ret:
        ret['systemctl'] = {}
    for topkey in ('blacklist', 'whitelist'):
        if topkey in data.get('systemctl', {}):
            if topkey not in ret['systemctl']:
                ret['systemctl'][topkey] = []
            for key, val in data['systemctl'][topkey].iteritems():
                if profile and isinstance(val, dict):
                    val['nova_profile'] = profile
                ret['systemctl'][topkey].append({key: val})

    return ret


def _get_tags(data):
    '''
    Retrieve all the tags for this distro from the yaml
    '''
    ret = {}
    distro = __grains__.get('osfinger')
    for toplist, toplevel in data.get('systemctl', {}).iteritems():
        for audit_dict in toplevel:
            for audit_id, audit_data in audit_dict.iteritems():
                tags_dict = audit_data.get('data', {})
                tags = None
                for osfinger in tags_dict:
                    if osfinger == '*':
                        continue
                    osfinger_list = [finger.strip() for finger in osfinger.split(',')]
                    for osfinger_glob in osfinger_list:
                        if fnmatch.fnmatch(distro, osfinger_glob):
                            tags = tags_dict.get(osfinger)
                            break
                    if tags is not None:
                        break
                # If we didn't find a match, check for a '*'
                if tags is None:
                    tags = tags_dict.get('*', [])
                # systemctl:blacklist:0:telnet:data:Debian-8
                if isinstance(tags, dict):
                    # malformed yaml, convert to list of dicts
                    tmp = []
                    for name, tag in tags.iteritems():
                        tmp.append({name: tag})
                    tags = tmp
                for item in tags:
                    for name, tag in item.iteritems():
                        tag_data = {}
                        # Whitelist could have a dictionary, not a string
                        if isinstance(tag, dict):
                            tag_data = copy.deepcopy(tag)
                            tag = tag_data.pop('tag')
                        if tag not in ret:
                            ret[tag] = []
                        formatted_data = {'name': name,
                                          'tag': tag,
                                          'module': 'systemctl',
                                          'type': toplist}
                        formatted_data.update(tag_data)
                        formatted_data.update(audit_data)
                        formatted_data.pop('data')
                        ret[tag].append(formatted_data)
	
    return ret

def _execute_shell_command(cmd):
    '''
    This function will execute passed command in /bin/shell
    '''
    return __salt__['cmd.run'](cmd, python_shell=True, shell='/bin/bash', ignore_retcode=True)


def _systemctl(service_name):
    '''
    Return service status.
    Return object will be like ('status_code', 'status') if {service_is_present} else ('status_code',)
    '''
    output = _execute_shell_command('systemctl is-enabled ' + service_name + ' 2>/dev/null; echo $?').strip()
    output = output.split('\n') if output != "" else []
    if output == []:
	return False
    return (output[1], output[0]) if len(output) == 2 else (output[0], "not_found")
