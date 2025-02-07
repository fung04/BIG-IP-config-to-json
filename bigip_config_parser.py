# Copyright 2022 F5 Networks, Inc.
# Modified work Copyright 2024 [fung04]
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Modifications:
# - Converted from JavaScript to Python
# - Converted parser.js to Python class BigIPConfigParser()
# - Restructured logic to accommodate Python's language constraints
# - Adjusted function implementation to achieve same functionality

import tarfile
import os
import re
import json
from typing import List, Dict, Any

CONFIG_OUTPUT_FOLDER = "config"
JSON_OUTPUT_FOLDER = "output"
FILE_EXTENSION = ".ucs"

class BigIPConfigParser():
    def __init__(self):
        self.topology_arr = []
        self.topology_count = 0
        self.longest_match_enabled = False

    @staticmethod
    def arr_to_multiline_str(arr: List[str]) -> Dict[str, str]:
        key, *rest = arr[0].strip().split()
        arr[0] = ' '.join(rest)
        return {key: '\n'.join(arr)}

    @staticmethod
    def count_indent(string: str) -> int:
        return len(string) - len(string.lstrip())

    @staticmethod
    def get_title(string: str) -> str:
        return re.sub(r'\s?\{\s?}?$', '', string).strip()

    @staticmethod
    def obj_to_arr(line: str) -> List[str]:
        return line.split('{')[1].split('}')[0].strip().split()

    @staticmethod
    def remove_indent(arr: List[str]) -> List[str]:
        return [line[4:] if BigIPConfigParser.count_indent(line) > 1 else line for line in arr]

    @staticmethod
    def str_to_obj(line: str) -> Dict[str, str]:
        key, *rest = line.strip().split()
        return {key: ' '.join(rest)}

    # Return true if the string contains the header of ltm/gtm/pem rule
    @staticmethod
    def is_rule(string: str) -> bool:
        return any(rule in string for rule in ('ltm rule', 'gtm rule', 'pem irule'))

    # Pass arr of individual bigip-obj
    # Recognize && handle edge cases
    def orchestrate(self, arr: List[str]) -> Dict[str, Any]:
        key = self.get_title(arr[0])
        
        # Below fix is likely related with Issues and PR discuss in f5devcentral/f5-automation-config-converter
        # Issues: Error "Missing or mis-indented '}'" #99
        # PR: Update parser.js #102 
        if len(arr) <= 1:
            return {key: {}}
        
        # Remove opening and closing brackets
        arr = arr[1:-1]  
        
        # Edge case: iRules (multiline string)
        if self.is_rule(key):
            return {key: '\n'.join(arr)}
        
        # Edge case: monitor min X of {...}
        if 'monitor min' in key:
            return {key: ' '.join(s.strip() for s in arr).split()}
        
        # Edge case: skip cli script
        # Also skip 'sys crypto cert-order-manager', it has quotation marks around curly brackets of 'order-info'
        if 'cli script' in key or 'sys crypto cert-order-manager' in key:
            return {key: {}}
        
        obj = {}
        i = 0
        while i < len(arr):
            line = arr[i]
            
            # Edge case: nested object
            # RECURSIVE FUNCTION
            # Quoted bracket "{" won't trigger recursion
            if line.endswith('{') and len(arr) != 1:
                c = next((j for j, l in enumerate(arr[i:], start=i) if l == '    }'), None)
                if c is None:
                    raise ValueError(f"Missing or mis-indented '}}' for line: '{line}'")
                sub_obj_arr = self.remove_indent(arr[i:c+1])
                
                # Coerce unnamed objects into array
                coerce_arr = [f"{j} {l}" if l == '    {' else l for j, l in enumerate(sub_obj_arr)]
                # Recursion for subObjects
                obj.update(self.orchestrate(coerce_arr))
                # Skip over nested block
                i = c
            
            # Edge case: empty object
            elif line.strip().endswith('{ }'):
                obj[line.split('{')[0].strip()] = {}
            
            # Edge case: pseudo-array pattern (coerce to array)
            elif '{' in line and '}' in line and '"' not in line:
                obj[line.split('{')[0].strip()] = self.obj_to_arr(line)
            
            # Edge case: single-string property
            elif (not line.strip().count(' ') or re.match(r'^"[\s\S]*"$', line.strip())) and '}' not in line:
                obj[line.strip()] = ''
            
            # Regular string property
            # Ensure string props on same indentation level
            elif self.count_indent(line) == 4:
                # Check if the line contains an odd number of double quotes, indicating an unclosed string
                if line.count('"') % 2 == 1:
                    # Find the next line that also contains an odd number of double quotes, which would close the string
                    for j, l in enumerate(arr[i:]):
                        if l.count('"') % 2 == 1:
                            c = j + i
                    # If no such line is found, raise an error indicating an unclosed quote
                    if c is None:
                        raise ValueError(f"Unclosed quote in multiline string starting at: '{line}'")
                    # Extract the chunk of lines between the current line and the closing line
                    chunk = arr[i:c+1]
                    # Convert the chunk of lines into a multiline string and update the object
                    obj.update(self.arr_to_multiline_str(chunk))
                    # Move the index to the closing line to continue processing
                    i = c
                
                # Treat as typical string
                else:
                    tmp = self.str_to_obj(line.strip())
                    if key.startswith('gtm monitor external') and 'user-defined' in tmp:
                        obj.setdefault('user-defined', {}).update(self.str_to_obj(tmp['user-defined']))
                    else:
                        obj.update(tmp)
            
            # Else report exception
            else:
                print(f"Unexpected line: {line}")
            
            i += 1
        
        return {key: obj}

    # THIS FUNCTION SHOULD ONLY GROUP ROOT-LEVEL CONFIG OBJECTS
    def group_objects(self, arr: List[str]) -> List[List[str]]:
        group = []
        i = 0
        while i < len(arr):
            current_line = arr[i]
            
            # Empty obj / pseudo-array
            # Change to use first/last char pattern (not nested empty obj)
            # Skip nested objects for now..
            if '{' in current_line and '}' in current_line and not current_line.startswith(' '):
                group.append([current_line])
            elif current_line.strip().endswith('{') and not current_line.startswith(' '):
                # Looking for non-indented '{'
                rule_flag = self.is_rule(current_line)
                # Different grouping logic for iRules
                bracket_count = 1
                c = 0
                while bracket_count != 0:
                    c += 1
                    # Count { and }. They should occur in pairs
                    line = arr[i + c]
                    if not ((line.strip().startswith('#') or line.strip().startswith('set') or 
                             line.strip().startswith('STREAM')) and rule_flag):
                        # Exclude quoted parts
                        updated_line = re.sub(r'\\"', '', line.strip())
                        updated_line = re.sub(r'"[^"]*"', '', updated_line)
                        
                        # Count brackets if functional (not stringified)
                        # Closing root-level obj
                        bracket_count += updated_line.count('{') - updated_line.count('}')
                    
                    # Abort if run into next rule
                    if self.is_rule(line):
                        c -= 1
                        break
     
                group.append(arr[i:i + c + 1])
                i += c
            i += 1
        return group

    def parse_files(self, files: Dict[str, str]) -> Dict[str, Any]:
        try:
            data = {}
            for key, value in files.items():
                 # Do not parse certs, keys or license
                if any(x in key for x in ('Common_d', 'bigip_script.conf', '.license')):
                    continue
                
                file_arr = value.replace('\r\n', '\n').split('\n')
                
                # GTM topology
                new_file_arr = []
                self.topology_arr = []
                self.topology_count = 0
                self.longest_match_enabled = False
                in_topology = False
                irule = 0
                
                for line in file_arr:
                    # Process comments in iRules
                    if irule == 0:
                        if line.strip().startswith('# '):
                            # Mark comments outside of irules with specific prefix
                            line = line.strip().replace('# ', '#comment# ')
                        elif self.is_rule(line):
                            irule += 1
                    # Don't count brackets in commented or special lines
                    elif not line.strip().startswith('#'):
                        irule += line.count('{') - line.count('}')
                    
                    if 'topology-longest-match' in line and 'yes' in line:
                        self.longest_match_enabled = True
                    elif line.startswith('gtm topology ldns:'):
                        in_topology = True
                        if not self.topology_arr:
                            self.topology_arr.extend(['gtm topology /Common/Shared/topology {', '    records {'])
                        ldns_index, server_index, bracket_index = (line.index(x) for x in ('ldns:', 'server:', '{'))
                        ldns = line[ldns_index + 5:server_index].strip()
                        server = line[server_index + 7:bracket_index].strip()
                        self.topology_arr.extend([
                            f"        topology_{self.topology_count} {{",
                            f"            source {ldns}",
                            f"            destination {server}"
                        ])
                        self.topology_count += 1
                    elif in_topology:
                        if line == '}':
                            in_topology = False
                            self.topology_arr.append('        }')
                        else:
                            self.topology_arr.append(f"        {line}")
                    else:
                        new_file_arr.append(line)
                
                if self.topology_arr:
                    self.topology_arr.extend([
                        f"        longest-match-enabled {str(self.longest_match_enabled).lower()}",
                        '    }',
                        '}'
                    ])
                
                file_arr = new_file_arr + self.topology_arr
                # Filter whitespace && found comments
                file_arr = [line for line in file_arr if line and not line.strip().startswith('#comment# ')]
                
                group_arr = [self.orchestrate(obj) for obj in self.group_objects(file_arr)]
                data.update({k: v for d in group_arr for k, v in d.items()})
            
            return data
        except Exception as e:
            # error_message = f"Error parsing input file. Please open an issue at https://github.com/f5devcentral/f5-automation-config-converter/issues and include the following error:\n{str(e)}"
            error_message = f"Error parsing input file. Error as following error:\n{str(e)}"
            raise Exception(error_message)
        
class BigIPConfigExtractor():
    def __init__(self):
        files = [file for file in os.listdir() if os.path.splitext(file)[1] ==FILE_EXTENSION]
        
        for file in files:
            file_name = file.replace(f'{FILE_EXTENSION}', '')
            try:
                print(f"Extracting [{file}]")
                with tarfile.open(file, 'r:gz') as tar:
                    # Extract all files within the 'config' directory to the destination folder
                    for member in tar.getmembers():
                        if member.name.startswith('config/') and '/' not in member.name[len('config/'):]:
                            # Remove the 'config/' prefix from the member name
                            member.name = member.name[len('config/'):]
                            if member.name.endswith('.conf'):
                                tar.extract(member, path=f"{CONFIG_OUTPUT_FOLDER}/{file_name}", set_attrs=False)
            except Exception as e:
                print(f"Error processing {file}:\n{e}")

if __name__ == "__main__":
    os.makedirs(CONFIG_OUTPUT_FOLDER, exist_ok=True)
    os.makedirs(JSON_OUTPUT_FOLDER, exist_ok=True)
    BigIPConfigExtractor()

    # read dirs in config folder, each dir contain multiple .conf files
    config_files = {}
    for dir in os.listdir(CONFIG_OUTPUT_FOLDER):
        for config_file in os.listdir(f"{CONFIG_OUTPUT_FOLDER}/{dir}"):
            with open(f"{CONFIG_OUTPUT_FOLDER}/{dir}/{config_file}", "r") as f:
                config_files[config_file] = f.read()
        
        json_dump = BigIPConfigParser().parse_files(config_files)
        print(f"\nParsed [{dir}] successfully")

        with open(f"{JSON_OUTPUT_FOLDER}/{dir}.json", "w") as f:
            json.dump(json_dump, f, indent=4)
        