import pickle
from socket import socket

from protocol.mesage import BaseMessage

def send_message(message: BaseMessage, sender: socket):
    bin_data = pickle.dump(message)
    sender.sendall(bin_data)

def receive_message_callback(receiver: socket) -> BaseMessage:
    buf = b''
    not_yet = True
    while not_yet:
        raw_data = receiver.recv(1024)
        buf += raw_data
        not_yet = len(raw_data) > 0
    return pickle.loads(buf)
        

    
