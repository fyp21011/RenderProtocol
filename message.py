
from abc import ABC
import pickle
import socket
import threading
from typing import Any, ByteString, Dict, List, Tuple, Union
import warnings

import numpy as np
import open3d as o3d


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
            BaseMessage._cnt_lock.release()

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
            warnings.warn(f"message {self.message_idx} of type {type(self)} failed because " + \
                error_reason + ". Retrying.")
            client.close()
            self.send(retry_times + 1) # retry
        
        # fail for 3 times: 
        elif isinstance(self, MeshesMessage) or \
            isinstance(self, AddRigidBodyPrimitiveMessage):
            client.close()
            raise Exception("critical message failed to be sent, because " + error_reason)
        else:
            client.close()
            warnings.warn(f"message {self.message_idx} of type {type(self)} failed again because " + \
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
            if isinstance(msg, BaseMessage):
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

class MeshesMessage(BaseMessage):
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
                bstr[sent_size: min(sent_size + MeshesMessage.CHUNK_SIZE, total_size)]
            ))
            sent_size = min(sent_size + MeshesMessage.CHUNK_SIZE, total_size)

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
    """
    Params
    ------
    primitive_name: the identifier of the primitive
    typename_in_bpy: the corresponding typename in the BPY
    params: the keyword parameters to create the primitive in the BPY
    """
    def __init__(self, primitive_name:str, typename_in_bpy: str, **params: Any) -> None:
        super().__init__()
        self.primitive_name = primitive_name
        self.primitive_type = typename_in_bpy
        self.params = params

    def create_primitive_in_blender(self):
        """ create the primitive in BPY
        """
        return eval(self.primitive_type)(**self.params)

class DeformableMeshesMessage(BaseMessage):
    """
    It is DEPRECATED to directly initialize a 
    DeformableMeshesMessage. An advisable way is to rely on
    the DeformableMeshesMessage.Factory class to generate
    the meshes from either pointcloud or sdf values.

    Params
    ------
    name: the object name
    frame_idx: the frame index at which the deformation is in effect
    particles: a (N, 3) array storing meshes vertices
    faces: a (M, 3) array, where each row is the vertex indices of one
        triangle face in this meshes
    """
    _name_2_frame_idx: Dict[str, int] = {}
    _frame_lock = threading.RLock()

    def __init__(self, name: str, frame_idx: int, particles: np.ndarray, faces: np.ndarray) -> None:
        super().__init__()
        self.obj_name = name
        self.frame_idx = frame_idx
        self.prev_frame_idx = None
        """ the frame idx of the previous message
        of the same object
        """
        self._update_frame_index()
        self.particles = particles
        self.faces = faces


    def _update_frame_index(self) -> None:
        """ Assign value to the `self.prev_frame_idx`

        This is thread-safe. 
        """
        DeformableMeshesMessage._frame_lock.acquire()
        try:
            self.prev_frame_idx = DeformableMeshesMessage._name_2_frame_idx.get(self.obj_name, None)
            DeformableMeshesMessage._name_2_frame_idx[self.obj_name] = self.frame_idx
        finally:
            DeformableMeshesMessage._frame_lock.release()

    def send(self, retry_times=0):
        # NOTE: the message will be wrapped in a MeshesMessage to send. You
        # may refer to the README regarding why it is designed in this way
        wrap_msg = MeshesMessage(f"MPM::MESHES::{self.obj_name}::{self.frame_idx}", pickle.dumps(self), None)
        return wrap_msg.send(retry_times)

    class Factory:
        """ Factory of DeformableMeshesMessage, used to re-construct the
        meshes from either pointcloud or signed distance function

        Params
        ------
        name: the object's name
        frame_idx: the 
        sdf: the SDF values
        pcd: the point clouds

        NOTE: either `pcd` or `sdf`, not both, not neither
        """
        def __init__(self, name: str, frame_idx: int, sdf = None, pcd = None) -> None:
            self.name = name
            self.frame_idx = frame_idx
            self.sdf = sdf
            self.pcd = pcd
            if (sdf is not None) and (pcd is not None):
                raise ValueError("PCD and SDF cannot be set together")
            if (sdf is None) and (pcd is None):
                raise ValueError("PCD and SDF cannot both be NONE")
        
        @classmethod
        def _face_reconstruction(cls, pcd: np.ndarray) -> o3d.geometry.TriangleMesh:
            # step 1: build a o3d pcd
            vertices = o3d.utility.Vector3dVector(pcd.reshape((-1, 3)))
            point_cloud = o3d.geometry.PointCloud(vertices)
            point_cloud.estimate_normals()
            # step 2: average the distance to get the radius
            distances = point_cloud.compute_nearest_neighbor_distance()
            radius = np.mean(distances) * 1.5
            meshes = o3d.geometry.TriangleMesh.create_from_point_cloud_ball_pivoting(
                point_cloud, 
                o3d.utility.DoubleVector([radius, radius * 2])
            )
            return meshes
        
        @property
        def message(self) -> "DeformableMeshesMessage":
            """ Generate the meshes and wrap it into a DeformableMeshesMessage

            If `pcd` is set, the meshes will be re-constructed using ball
            pivoting; otherwise, when the `sdf` is set, Open3D's RGBD
            integration will be used to re-construct the meshes

            Return
            ------
            The generated DeformableMeshesMessage
            """
            if self.pcd is not None:
                o3d_mesh = DeformableMeshesMessage.Factory._face_reconstruction(self.pcd)
            else:
                pass
            np_particles = np.asarray(o3d_mesh.vertices)
            np_faces = np.asarray(o3d_mesh.triangles)
            particles = [np_particles[i, :] for i in range(np_particles.shape[0])]
            faces = [np_faces[i, :] for i in range(np_faces.shape[0])]
            return DeformableMeshesMessage(self.name, self.frame_idx, particles, faces)

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

class FinishAnimationMessage(BaseMessage):
    """The message marks the end of animation

    The message will cease the renderer server, so no
    more message can be sent after this message.

    Params
    ------
    exp_name: the experiment name, which will be used
        by the renderer as the file saving name
    end_frame_idx: the end frame index of the animation
    """
    def __init__(self, exp_name: str, end_frame_idx: int) -> None:
        super().__init__()
        self.end_frame_idx = end_frame_idx
        self.exp_name = exp_name
