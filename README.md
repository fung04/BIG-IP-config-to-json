# BIG-IP-config-to-json
A Python tool helps converting UCS (User Configuration Set) archive files into a structured JSON format. The parser logic is adapted from [f5devcentral/f5-automation-config-converter](https://github.com/f5devcentral/f5-automation-config-converter), converted from JavaScript to Python.

### Key Features:
- Converts BIG-IP UCS archive files to JSON
- Python implementation of F5's parser functionality

### Usage
1. Place your UCS file and `bigip_config_parser.py` in the same directory
2. Run the script to process the UCS file
3. The script will create two folders:
   - `config/`: Contains extracted configuration files from UCS
   - `output/`: Contains the parsed JSON files

### Note
This project is a Python port of the parser component from F5's automation config converter tool. Original parser.js code is licensed under Apache License 2.0 by F5 Networks, Inc.
