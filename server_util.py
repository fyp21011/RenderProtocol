import asyncio
from datetime import datetime
import pickle
from typing import Callable
import numpy as np

import open3d as o3d

from .message import BaseMessage, ResponseMessage, AddRigidBodyMeshMessage, SetParticlesMessage

class AddMeshMessageHandler:
    """ A middleware to merge chunks into its AddRigidBodyMeshMessage

    Params
    ------
    next_handler: the method to deal with the reconstructed fully-
        received AddRigidBodyMeshMessage, or other messages 
    """
    def __init__(self, next_handler: Callable[[BaseMessage], None]):
        self.mesh_name_2_msg = {}
        self.mesh_name_2_chunks = {}
        self.handler = next_handler
    
    def __call__(self, msg: BaseMessage):
        if isinstance(msg, AddRigidBodyMeshMessage):
            self.mesh_name_2_msg[msg.mesh_name] = msg
        elif isinstance(msg, AddRigidBodyMeshMessage.Chunk):
            name = msg.mesh_name
            if name not in self.mesh_name_2_chunks:
                self.mesh_name_2_chunks[name] = [msg]
            else:
                self.mesh_name_2_chunks[name].append(msg)
            if name in self.mesh_name_2_msg and \
                len(self.mesh_name_2_chunks[name]) == self.mesh_name_2_msg[name].chunk_num:
                self.mesh_name_2_chunks[name].sort(key = lambda x: x.chunk_id)
                for chunk in self.mesh_name_2_chunks[name]:
                    msg.chunks.append(chunk)
                self.handler(msg)
        else:
            self.handler(msg)

class SetParticleMessageHandler:
    """ A middleware to re-construce the surface from particles

    Params
    ------
    next_handler: the method to deal with the message AFTER
        the middleware completes
    """
    def __init__(self, next_handler: Callable[[BaseMessage], None]) -> None:
        self.handler = next_handler

    def __call__(self, msg: BaseMessage):
        if isinstance(msg, SetParticlesMessage):
            vertices = o3d.utility.Vector3dVector(msg.particles.reshape((-1, 3)))
            point_cloud = o3d.geometry.PointCloud(vertices)
            meshes = o3d.geometry.TriangleMesh.create_from_point_cloud_alpha_shape(point_cloud, 0.8)
            msg.particles = np.asarray(meshes.vertices)
            msg.faces = np.asarray(meshes.triangles)
        self.handler(msg)

class AsyncServer:
    """ An async server
    Params
    ------
    message_handler: a callback to hangle the incoming message
        
    **NOTE** You don't need to care about the chunks of a mesh
    file, because the above middleware will merge the chunks into
    one AddMeshMessageHandler
    """
    def __init__(self, message_handler: Callable[[BaseMessage], None], logger:Callable[[str], None] = None) -> None:
        self.message_handler = AddMeshMessageHandler(message_handler)
        self.message_handler = SetParticleMessageHandler(self.message_handler)
        self.logger = logger if logger else (lambda s: print('[DEBUG]', datetime.now(), s))

    async def _handle_incoming_request(self, reader: asyncio.StreamReader, writer):
        """ When there is request coming from the client, the
        method retrieve the message object from the request,
        verify the message, respond to the client and finally
        invoke the callback `message_handler` to deal with the
        message

        Params
        ------
        reader: from which the request is to be read
        writer: to which the response will be written
        """
        bstr, done = b'', False
        while not done:
            line = await reader.read(1024)
            bstr += line
            done = len(line) < 1024
        
        self.logger(f"{len(bstr)} bytes are read")
        request, err = BaseMessage.unpack(bstr)
        self.logger(f"No.{request.message_idx if request != None else 'Unknow'} message is decoded with error: {err}, preparing response")
        if request != None:
            response = ResponseMessage(request.message_idx, err)
        else:
            response = ResponseMessage(0, err)
        writer.write(pickle.dumps(response))
        await writer.drain()
        self.logger(f"No.{request.message_idx if request != None else 'Unknow'} message's response has been sent")
        writer.close()
        self.logger(f"connection terminated")
        if not err:
            self.message_handler(request)

    async def run_server(self):
        """ Start the server

        Call asyncio.run(server.run_server()) in the main
        to start.
        """
        self.logger(f"starting server at 127.0.0.1:{BaseMessage.port}")
        server = await asyncio.start_server(
            self._handle_incoming_request,
            '127.0.0.1',
            BaseMessage.port
        )
        async with server:
            await server.serve_forever()
    
