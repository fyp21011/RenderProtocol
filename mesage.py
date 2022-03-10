
from abc import ABC, abstractproperty
from enum import Enum
import pickle
import socket
import threading
from typing import Any, Dict, Tuple
import warnings

class MessageType(Enum):
    DEFAULT_MSG = 0
    ADD_MESH_MSG = 1
    ADD_PRIMITIVE_MSG = 2
    SET_PARTICLE_MSG = 3
    UPDATE_MESH_POSE = 4
    UPDATE_PRIMITIVE_POSE = 5
    UPDATE_FRAME = 6
    RESPONSE = 7


class BaseMessage(ABC):
    """ Base message for all the messages that
    can be exchanged through the protocol
    """
    _message_cnt = 1
    _cnt_lock = threading.RLock()
    ip = 'localhost'
    port = '4490'
    def __init__(self) -> None:
        """ The super.init will assign a global
        unique id to each message.
        """
        self.message_idx = 0
        self.set_idx_and_increment_cnt()
        self.client = None
        """IPv4 TCP socket"""

    @abstractproperty
    def type(self) -> MessageType:
        """ type of this message
        """
        return MessageType.DEFAULT_MSG

    def set_idx_and_increment_cnt(self) -> None:
        """ generate a global unique id for this message
        """
        self._cnt_lock.acquire()
        try:
            self.message_idx = self._message_cnt
            self._message_cnt += 1
        finally:
            self._cnt_lock.release

    def _prepare_connection(self) -> socket.socket:
        """ Establish a Ipv4 TCP connection to the server

        Return
        ------
        the socket connection
        """
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client.connect((self.ip, self.port))

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
        if self.client == None:
            self._prepare_connection()
        
        # send & receive
        bin_data = pickle.dumps(self)
        self.client.sendall(bin_data)
        bstr = self.client.recv(1024)
        response = pickle.loads(bstr)

        # error handling
        if not isinstance(response, ResponseMessage):
            error_reason = "corrupted response"
        elif response.message_idx != self.message_idx:
            error_reason = f"REQ_IDX={self.message_idx}, RES_IDX={response.message_idx}"
        else:
            error_reason = response.err_msg

        if len(error_reason) == 0:
            self.client.close()
        elif retry_times < 3:
            warnings.warn(f"message {self.message_idx} of type {self.type} failed because " + \
                error_reason + ". Retrying.")
            self.send(retry_times + 1) # retry
        elif self.type == MessageType.ADD_MESH_MSG or self.type == MessageType.ADD_PRIMITIVE_MSG:
            self.client.close()
            raise "critical message failed to be sent, because " + error_reason
        else:
            self.client.close()
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
    
    def type(self) -> MessageType:
        return MessageType.RESPONSE

class AddRigidBodyMeshMessage(BaseMessage):
    """
    Params
    ------
    mesh_name: name of the mesh files, together with the extension suffix
    mesh_file: the content of the mesh file
    init_pose: an 4-by-4 np.ndarray, describing the initial pose of the mesh
    """
    def __init__(self, mesh_name: str, mesh_file, init_pose) -> None:
        super().__init__()
        self.mesh_name = mesh_name
        self.mesh_file = mesh_file
        self.init_pose = init_pose

    def type(self) -> MessageType:
        return MessageType.ADD_MESH_MSG


class AddRigidBodyPrimitiveMessage(BaseMessage):
    def __init__(self, primitive_name:str, typename_in_bpy: str, params: Dict[str, Any]) -> None:
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

    def type(self) -> MessageType:
        return MessageType.ADD_PRIMITIVE_MSG

class SetParticlesMessage(BaseMessage):
    def __init__(self) -> None:
        #TODO
        super().__init__()
    
    def type(self) -> MessageType:
        return MessageType.SET_PARTICLE_MSG

class UpdateRigidBodyMeshPoseMessage(BaseMessage):
    """
    Params
    ------
    mesh_name: which mesh should be updated
    pose: the new pose matrix
    """
    def __init__(self, mesh_name: str, pose) -> None:
        super().__init__()
        assert pose.shape == (4, 4), \
            f"the pose of a mesh is expected to be a (4, 4) matrix, but got a {pose.shape}"
        self.mesh_name = mesh_name
        self.pose_mat = pose
    
    def type(self) -> MessageType:
        return MessageType.UPDATE_MESH_POSE

class UpdateRigidBodyPrimitiveMessage(BaseMessage):
    """
    Params
    ------
    primitive_name: which primitive should be updated
    xyz_quat: the 7-dim describer to determine the new pose
    """
    def __init__(self, primitive_name: str, xyz_quat) -> None:
        super().__init__()
        self.primitive_name = primitive_name
        self.xyz_quat = xyz_quat

    def type(self) -> MessageType:
        return MessageType.UPDATE_PRIMITIVE_POSE

class UpdateFrameMessage(BaseMessage):
    """ Mark a frame. For example, 
    ```
    [10] UpdateFrameMessage(24)
    [11] UpdateRigidBody...
    [12] UpdateRigidBody...
    [13] SetParticlesMessage...
    [14] UpdateFrameMessage(25)
    ```
    The message [11], [12], [13] all apply changes to the
    frame 25. The messages after message [14] or before
    message [10] have no effect on the frame 25.  

    Params
    ------
    fidx: frame idx
    """
    def __init__(self, fidx: int) -> None:
        super().__init__()
        self.frame_idx = fidx
    
    def type(self) -> MessageType:
        return MessageType.UPDATE_FRAME

