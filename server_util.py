import asyncio
from chunk import Chunk
from datetime import datetime
import pickle
from typing import Callable, Dict
import numpy as np

import open3d as o3d

from .message import BaseMessage, ResponseMessage, MeshesMessage, DeformableMeshesMessage

class MeshChunksHandler:
    """ A middleware to merge chunks into its MeshesMessage

    Params
    ------
    next_handler: the method to deal with the reconstructed fully-
        received AddRigidBodyMeshMessage, or other messages 
    """
    def __init__(self, next_handler: Callable[[BaseMessage], None]):
        self.mesh_name_2_msg:    Dict[str, MeshesMessage] = {}
        self.mesh_name_2_chunks: Dict[str, Chunk] = {}
        self.handler = next_handler
    
    def __call__(self, msg: BaseMessage):
        if isinstance(msg, MeshesMessage):
            self.mesh_name_2_msg[msg.mesh_name] = msg
        elif isinstance(msg, MeshesMessage.Chunk):
            name = msg.mesh_name
            if name not in self.mesh_name_2_chunks:
                self.mesh_name_2_chunks[name] = [msg]
            else:
                self.mesh_name_2_chunks[name].append(msg)
            # check whether all the chunks has been collected
            if name in self.mesh_name_2_msg and \
                len(self.mesh_name_2_chunks[name]) == self.mesh_name_2_msg[name].chunk_num:
                self.mesh_name_2_chunks[name].sort(key = lambda x: x.chunk_id)
                meshmsg = self.mesh_name_2_msg[name]
                for chunk in self.mesh_name_2_chunks[name]:
                    meshmsg.chunks.append(chunk)
                del self.mesh_name_2_chunks[name]
                del self.mesh_name_2_msg[name]
                if name.startswith("MPM::MESHES::"):
                    # a open3d re-constructed meshes from point cloud
                    pcdMessage: DeformableMeshesMessage = pickle.loads(meshmsg.mesh_file)
                    self.handler(pcdMessage)
                else:
                    # a nomal meshes
                    self.handler(meshmsg)
        else:
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
        self.message_handler = MeshChunksHandler(message_handler)
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
        self.logger(f"No.{request.message_idx if request != None else 'Unknow'} message of type {type(request)} is decoded with error: {err}, preparing response")
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
    
