
from abc import ABC
from ctypes import Union
import pickle
import socket
import threading
from typing import Any, ByteString, List, Tuple
import warnings

import numpy as np


class BaseMessage(ABC):
    """ Base message for all the messages that
    can be exchanged through the protocol
    """
    _message_cnt = 1
    _cnt_lock = threading.RLock()
    ip = 'localhost'
    port = 4490
    def __init__(self) -> None:
        """ The super.init will assign a global
        unique id to each message.
        """
        self.message_idx = 0
        self.set_idx_and_increment_cnt()

    def set_idx_and_increment_cnt(self) -> None:
        """ generate a global unique id for this message
        """
        BaseMessage._cnt_lock.acquire()
        try:
            self.message_idx = self._message_cnt
            BaseMessage._message_cnt += 1
        finally:
            BaseMessage._cnt_lock.release

    def _prepare_connection(self) -> socket.socket:
        """ Establish a Ipv4 TCP connection to the server

        Return
        ------
        the socket connection
        """
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect((self.ip, self.port))
        return client

    def send(self, retry_times = 0):
        """ Send the message

        If the connection is not established, first establish the
        connection and then send the message.
        If the message sending fails, retry the sending until the 
        retry_times == 3. If the message still cannot be sent when
        retry_times == 3, a error will be raised if the message
        is critical (those adding something to the renderer), or
        the message will simply be discarded.

        Params
        ------
        retry_times: retry times, if this parameter >= 2, no
            retry if the sending fails
        """
        client = self._prepare_connection()
        
        # send & receive
        bin_data = pickle.dumps(self)
        client.sendall(bin_data)
        bstr = client.recv(1024)
        response = pickle.loads(bstr)
        # error handling
        if not isinstance(response, ResponseMessage):
            error_reason = "corrupted response"
        elif response.message_idx != self.message_idx:
            error_reason = f"REQ_IDX={self.message_idx}, RES_IDX={response.message_idx}"
        else:
            error_reason = response.err_msg

        if len(error_reason) == 0:
            # succeed
            client.close()
        
        elif retry_times < 3:
            # failed, re-try 
            warnings.warn(f"message {self.message_idx} of type {self.type} failed because " + \
                error_reason + ". Retrying.")
            client.close()
            self.send(retry_times + 1) # retry
        
        # fail for 3 times: 
        elif isinstance(self, AddRigidBodyMeshMessage) or \
            isinstance(self, AddRigidBodyPrimitiveMessage):
            client.close()
            raise "critical message failed to be sent, because " + error_reason
        else:
            client.close()
            warnings.warn(f"message {self.message_idx} of type {self.type} failed again because " + \
                error_reason + ". Won't retry")

    @classmethod
    def unpack(cls, bstring) -> Tuple["BaseMessage", str]:
        """ Construct the message object from binary pickled string
        which is expected to be received from sockets.

        Params
        ------
        bstring: the binary pickled string reaad from sockets

        Returns
        -------
        The message, as well as an error string, if the message
        cannot be constructed. 
        """
        try:
            msg = pickle.loads(bstring)
            if isinstance(msg, BaseMessage) and hasattr(msg, 'type'):
                err = ""
            else:
                err = f"what is received is not a BaseMessage, but a {type(msg)}"
        except pickle.UnpicklingError as e:
            msg = None
            err = str(e)
        return msg, err
       

class ResponseMessage(BaseMessage):
    """
    Params
    ------
    message_idx: the idx of the request message
    err_msg: error message, empty if no error
    """
    def __init__(self, message_idx: int, err_msg: str) -> None:
        self.message_idx = message_idx
        self.err_msg = err_msg

class AddRigidBodyMeshMessage(BaseMessage):
    """
    Params
    ------
    mesh_name: name of the mesh files, together with the extension suffix
    mesh_file: the content of the mesh file
    init_pose: an 4-by-4 np.ndarray, describing the initial pose of the mesh
    """
    def __init__(self, mesh_name: str, mesh_file:ByteString, init_pose: np.ndarray) -> None:
        super().__init__()
        self.mesh_name = mesh_name
        self.init_pose = init_pose

        self.chunks = []
        self._split_file_content_to_chunks(mesh_file)
        self.chunk_num = len(self.chunks)

    CHUNK_SIZE = 61440 # 60KB
    class Chunk(BaseMessage):
        def __init__(self, mesh_name:str, chunk_id: int, chunk) -> None:
            super().__init__()
            self.mesh_name = mesh_name
            self.chunk_id = chunk_id
            self.chunk = chunk


    def _split_file_content_to_chunks(self, bstr: ByteString) -> List[Chunk]:
        sent_size = 0
        chunks = []
        total_size = len(bstr)
        while sent_size < total_size:
            self.chunks.append(self.Chunk(
                self.mesh_name,
                len(chunks),
                bstr[sent_size: min(sent_size + AddRigidBodyMeshMessage.CHUNK_SIZE, total_size)]
            ))
            sent_size = min(sent_size + AddRigidBodyMeshMessage.CHUNK_SIZE, total_size)

    def send(self, retry_times=0):
        chunks = self.chunks
        self.chunks = []
        super().send(retry_times)
        
        for chunk in chunks:
            chunk.send(retry_times)
        self.chunks = chunks

    @property
    def mesh_file(self) -> ByteString:
        bstr = b''
        for chunk in self.chunks:
            bstr += chunk.chunk
        return bstr
    
class AddRigidBodyPrimitiveMessage(BaseMessage):
    def __init__(self, primitive_name:str, typename_in_bpy: str, **params: Any) -> None:
        """
        Params
        ------
        primitive_name: the identifier of the primitive
        typename_in_bpy: the corresponding typename in the BPY
        params: the keyword parameters to create the primitive in the BPY
        """
        super().__init__()
        self.primitive_name = primitive_name
        self.primitive_type = typename_in_bpy
        self.params = params

    def create_primitive_in_blender(self):
        """ create the primitive in BPY
        """
        return eval(self.primitive_type)(**self.params)

class SetParticlesMessage(BaseMessage):
    def __init__(self, particles: np.ndarray, name: str, frame_idx: int) -> None:
        #TODO
        super().__init__()
        self.particles = particles
        self.obj_name  = name
        self.frame_idx = frame_idx

class UpdateRigidBodyPoseMessage(BaseMessage):
    """
    Params
    ------
    name: identifier of the rigid-body object to be updated
    pose: the new pose vector of dim 7
    frame_idx: the frame idx at which the update is in effect
    """
    def __init__(self, name: str, pose: Union[np.ndarray, List[float]], frame_idx: int) -> None:
        super().__init__()
        assert len(pose) == 7, \
            f"the pose of a mesh is expected to be a 7-dim vector, but got a {pose}"
        self.name = name
        self.pose_vec = pose
        self.frame_idx = frame_idx

