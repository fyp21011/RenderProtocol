import asyncio
import pickle
from typing import Callable

from protocol.mesage import BaseMessage, ResponseMessage

class AsyncServer:
    """ An async server
    Params
    ------
    message_handler: a callback to hangle the incoming message
    """
    def __init__(self, message_handler: Callable[[BaseMessage], None]) -> None:
        self.message_handler = message_handler

    async def _handle_incoming_request(self, reader, writer):
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
            request = await reader.read(1024)
            bstr += request
            done = len(request) == 0
        
        request, err = BaseMessage.unpack(bstr)
        response = ResponseMessage(request.message_idx, err)
        writer.write(pickle.dumps(response))
        await writer.drain()
        writer.close()
        if not err:
            self.message_handler(request)

    async def run_server(self):
        """ Start the server

        Call asyncio.run(server.run_server()) in the main
        to start.
        """
        server = await asyncio.start_server(
            self._handle_incoming_request,
            'localhost',
            BaseMessage.port
        )
        async with server:
            await server.serve_forever()
    
