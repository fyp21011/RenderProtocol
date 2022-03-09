
from abc import ABC, abstractproperty
from enum import Enum
import threading
from typing import Any, Dict

class MessageType(Enum):
    DEFAULT_MSG = 0
    ADD_MESH_MSG = 1
    ADD_PRIMITIVE_MSG = 2
    SET_PARTICLE_MSG = 3
    UPDATE_MESH_POSE = 4
    UPDATE_PRIMITIVE_POSE = 5
    UPDATE_FRAME = 6


class BaseMessage(ABC):
    _message_cnt = 1
    _cnt_lock = threading.RLock()
    def __init__(self) -> None:
        self.message_idx = 0
        self.set_idx_and_increment_cnt()

    @abstractproperty
    def type(self) -> MessageType:
        return MessageType.DEFAULT_MSG

    def set_idx_and_increment_cnt(self):
        self._cnt_lock.acquire()
        try:
            self.message_idx = self._message_cnt
            self._message_cnt += 1
        finally:
            self._cnt_lock.release



class AddRigidBodyMeshMessage(BaseMessage):
    def __init__(self, mesh_name: str, mesh_file, init_pose) -> None:
        super().__init__()
        self.mesh_name = mesh_name
        self.mesh_file = mesh_file
        self.init_pose = init_pose

    def type(self) -> MessageType:
        return MessageType.ADD_MESH_MSG


class AddRigidBodyPrimitiveMessage(BaseMessage):
    def __init__(self, primitive_name:str, typename_in_bpy: str, params: Dict[str, Any]) -> None:
        super().__init__()
        self.primitive_name = primitive_name
        self.primitive_type = typename_in_bpy
        self.params = params

    def create_primitive_in_blender(self):
        # check import
        return eval(self.primitive_type)(**self.params)

    def type(self) -> MessageType:
        return MessageType.ADD_PRIMITIVE_MSG

class SetParticlesMessage(BaseMessage):

    def __init__(self) -> None:
        super().__init__()
    
    def type(self) -> MessageType:
        return MessageType.SET_PARTICLE_MSG

class UpdateRigidBodyMeshPoseMessage(BaseMessage):
    def __init__(self, mesh_name: str, pose) -> None:
        super().__init__()
        assert pose.shape == (4, 4), \
            f"the pose of a mesh is expected to be a (4, 4) matrix, but got a {pose.shape}"
        self.mesh_name = mesh_name
        self.pose_mat = pose
    
    def type(self) -> MessageType:
        return MessageType.UPDATE_MESH_POSE

class UpdateRigidBodyPrimitiveMessage(BaseMessage):
    def __init__(self, primitive_name: str, xyz_quat) -> None:
        super().__init__()
        self.primitive_name = primitive_name
        self.xyz_quat = xyz_quat

    def type(self) -> MessageType:
        return MessageType.UPDATE_PRIMITIVE_POSE

class UpdateFrameMessage(BaseMessage):
    def __init__(self, fidx: int) -> None:
        super().__init__()
        self.frame_idx = fidx
    
    def type(self) -> MessageType:
        return MessageType.UPDATE_FRAME

