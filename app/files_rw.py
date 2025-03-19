import ast
import os
import csv
import pickle
import re
import shutil
from configparser import ConfigParser
from datetime import datetime
from tempfile import NamedTemporaryFile
from typing import Literal
import dill


class CsvRW:
    def __init__(self,csv_file_path:str):
        self.reader=None
        self.writer=None
        self.readline = None
        self.keys=[]
        self.f=None
        self.temp_file=None
        self.csv_file_path=None
        if os.path.exists(csv_file_path):
            self.csv_file_path=csv_file_path
        else:
            file=open(csv_file_path,"w")
            file.close()
            del file
            if os.path.exists(csv_file_path):
                self.csv_file_path = csv_file_path
            else:
                raise FileNotFoundError('no csv found in path, unable to create it')

    def __del__(self):
        self.close_if_open()
        return None

    def read_normal(self):
        self.close_if_open()
        self.f = open(self.csv_file_path)
        self.reader = csv.DictReader(self.f)
        self.readline = self.line_read_iterate()

    def read_backward(self):
        self.close_if_open()
        self.f = open(self.csv_file_path)
        self.keys = self.f.readline().strip().split(',')
        self.f.close()
        self.f = open(self.csv_file_path, 'rb')
        self.f.seek(0, os.SEEK_END)
        self.readline = self.get_previous_line

    def get_next_line(self):
        line=next(self.reader,None)
        if line is None:
            return self.__del__()
        else:
            line=correct_types_from_strings([line])[0]
            return line

    def line_read_iterate(self):
        for line in self.reader:
            line=correct_types_from_strings([line])[0]
            yield line
        del self.reader
        self.f.close()
        return

    def get_previous_line(self):
        try:  # catch OSError in case of a one line file
            while self.f.read(1) != b'\n':
                self.f.seek(-2, os.SEEK_CUR)
            line = self.f.readline().decode()
            self.f.seek(-2 - len(line), os.SEEK_CUR)
            line = dict(zip(self.keys, eval(line.strip())))
            return correct_types_from_strings([line])[0]
        except OSError as err:
            self.f.seek(0)
            return self.__del__()


    def close_if_open(self):
        if self.f is not None and not self.f.closed:
            self.f.close()
            self.f=None
        if self.temp_file is not None and not self.temp_file.closed:
            self.temp_file.close()
            if os.path.exists(self.temp_file.name):
                os.unlink(self.temp_file.name)
            self.temp_file=None

    def write_to_csv(self,mode:Literal['w','a'],keys:list=None):
        self.close_if_open()
        self.f = open(file=self.csv_file_path,mode=mode,newline='')
        self.writer = csv.writer(self.f)
        if keys is not None:self.writer.writerow(keys)
        return

    def write_line(self,row:list):
        self.writer.writerow(row)

    def read_write_to_csv(self):
        self.close_if_open()
        self.f=open(self.csv_file_path)
        self.reader=csv.DictReader(self.f)
        self.readline=self.line_read_iterate()
        self.temp_file=NamedTemporaryFile("w",dir=os.path.dirname(self.csv_file_path),delete=False)
        self.writer=csv.writer(self.temp_file)
        return

    #Append new lines, only if lines don't exist
    def safe_append_to_csv(self,lines:list):
        if len(lines)>0:
            self.close_if_open()
            self.read_backward()
            first_line=self.get_previous_line()
            self.write_to_csv('a')
            if first_line is not None:
                newest = first_line['Time'] 
            else: 
                newest = 0
                self.writer.writerow(list(lines[0].keys()))
            for line in lines:
                if line['Time']<=newest:continue
                self.write_line(list(line.values()))
            self.close_if_open()

    def save_and_replace(self):
        os.rename(self.temp_file.name,self.csv_file_path)
        self.close_if_open()

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
def write_config_file(_config_file,_parameters:dict):
    config = ConfigParser()
    for key,val in _parameters.items():
        config[key] = val
    with open(_config_file, 'w') as configfile:  # save
        config.write(configfile)
    return True

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

def config_update(_config_file,_last_modified):
    last_modified=os.path.getmtime(_config_file)
    if _last_modified is not None and last_modified > _last_modified:
        parameters=read_config_file(_config_file)
        return last_modified,parameters
    else:
        return last_modified,None

def save_state(_state_file,_object):
    with open(_state_file, 'wb') as file:
        dill.dump(_object, file)
    return True

def restore_state(_state_file):
    create_if_not_exists(_state_file)
    with open(_state_file, 'rb') as file:
        try:
            _object  = dill.load(file)
            return _object
        except EOFError as err:
            print(err)
            pass

def list_file_names(_directory):
    files = [file.split('.')[0] for file in os.listdir(_directory)]
    return files
def create_if_not_exists(_destination_file,_source_file=None):
    if not os.path.exists(_destination_file):
        dir_path, file_name = os.path.split(_destination_file)
        os.makedirs(dir_path,exist_ok=True) #Create path if not exist
        if _source_file is not None:
            shutil.copyfile(_source_file,_destination_file)
        else:
            with open(_destination_file,'w') as file:
                pass

