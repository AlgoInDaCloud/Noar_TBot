import ast
import os
import csv
import re
from configparser import ConfigParser
from datetime import datetime

def csv_to_dicts(csv_file_path):
    datas = list()
    if os.path.exists(csv_file_path):
        with open(csv_file_path, 'r') as file:
            csv_file = csv.DictReader(file)
            for row in csv_file:
                datas.append(dict(row))
    return datas

def dicts_to_csv(datas,csv_file_path,append):
    mode= 'a' if append else 'w'
    with open(csv_file_path, mode, newline='') as file:
        writer = csv.writer(file)
        if mode=='w':
            writer.writerow(datas[0].keys())
        for row in datas:
            writer.writerow(list(row.values()))
        print(f"{len(datas)} new lines saved to {csv_file_path}")

def read_config_file(_config_file):
    config = ConfigParser()
    config.read(_config_file)
    parameters=dict()
    for section in config.sections():
        _params=correct_types_from_strings([dict(config[section])])[0]
        parameters[section]=dict()
        for (key, val) in _params.items():
            parameters[section][key]=val
    return parameters

def correct_types_from_strings(list_of_dict):
    date_pattern=r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'
    for index, dicts in enumerate(list_of_dict):
        for key, value in dicts.items():
            if value=="" or value =="nan" or value=="None":
                list_of_dict[index][key]=None
            elif isinstance(value, str):
                if re.match(date_pattern, value):
                    list_of_dict[index][key]=datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
                else:
                    try:
                        list_of_dict[index][key] = ast.literal_eval(value)
                    except (SyntaxError,ValueError):
                        list_of_dict[index][key]=value
            else:
                list_of_dict[index][key] = value
    return list_of_dict