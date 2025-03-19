import threading
import re

def get_thread_by_name(name):
    for thread in threading.enumerate():
        if thread.name == name:
            return thread
    return None

def stop_thread_by_name(name):
    for thread in threading.enumerate():
        if thread.name == name:
            thread.stop()
            return True
    return False

def get_bots_threads():
    bot_threads=[]
    for thread in threading.enumerate():
        if re.fullmatch(r"(\w+)-bot(\d+)",thread.name):
            bot_threads.append(thread)
    return bot_threads

