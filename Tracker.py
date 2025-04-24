import socket
import threading
import keyboard
import uuid

from flask import Flask, request, jsonify

tracker_flask = Flask(__name__)


# Tracker Server
class Tracker:
    def __init__(self, host='0.0.0.0', port=6882):
        self.host = host
        self.port = port
        print('host: ', host, 'port: ', port)
        self.peer_swarms = {}  # Dictionary of swarms to store peer information has the same torrent file
        # self.tracker_url = f'http://{host if host != '0.0.0.0' else '127.0.0.1'}:{self.port}/announce'
        self.tracker_id = {}
        tracker_flask.add_url_rule('/announce', view_func=self.handle_peer_request, methods=['GET'])
        tracker_flask.run(host=self.host, port=self.port)

    def handle_peer_request(self):
        data = request.args
        swarm = self.find_in_swarm(data.get('info_hash'))
        # print('handle func invoked')
        if data.get('event') == 'started':
            print('started event')
            peer = self.generate_peer(data)
            if swarm is None:  # Found a list of peer has that torrent file
                # print('Swarm is created')
                self.peer_swarms[data.get('info_hash')] = {data.get('peer id'): peer}
            else:
                # print('Found a match swarm')
                if data.get('peer id') not in swarm:
                    self.peer_swarms[data.get('info_hash')][data.get('peer id')] = peer

            # print(f"info hash: {data.get('info_hash')} swarm: {self.peer_swarms[data.get('info_hash')].values()}")
            peer_list = [specific_peer_in_swarm for specific_peer_in_swarm in list(self.peer_swarms[data.get('info_hash')].values()) if peer != specific_peer_in_swarm]
            response = {'Tracker id': str(uuid.uuid4()), 'Peers': peer_list}
            # print('Going to return', response)
            return jsonify({'Tracker id': str(uuid.uuid4()), 'Peers': peer_list})
        elif data.get('event') == 'completed':
            print('completed event')
            peer = self.generate_peer(data)
            self.peer_swarms[data.get('info_hash')][data.get('peer id')] = peer
            return jsonify({})
        elif data.get('event') == 'stopped':
            if data.get('info_hash') in self.peer_swarms:
                if data.get('peer id') in self.peer_swarms[data.get('info_hash')]:
                    del self.peer_swarms[data.get('info_hash')][data.get('peer id')]
                    if len(self.peer_swarms[data.get('info_hash')]) == 0:
                        del self.peer_swarms[data.get('info_hash')]
            return jsonify({})
        elif data.get('event') == 'regular_check':
            if data.get('info_hash') in self.peer_swarms:
                if data.get('peer id') in self.peer_swarms[data.get('info_hash')]:
                    peer = self.peer_swarms[data.get('info_hash')][data.get('peer id')]
                    peer_list = [specific_peer_in_swarm for specific_peer_in_swarm in list(self.peer_swarms[data.get('info_hash')].values()) if peer != specific_peer_in_swarm]
                    return jsonify({'Tracker id': str(uuid.uuid4()), 'Peers': peer_list})
                else:
                    return jsonify({})
            else:
                return jsonify({})

    def generate_peer(self, data):
        is_seeder_peer = True if data.get('event') == 'completed' else False
        peer = {
            'peer id': data.get('peer id'),
            'listen ip': data.get('listen ip'),
            'port': data['port'],
            'is_seeder': is_seeder_peer
        }
        return peer

    def find_in_swarm(self, info_hash: str):
        return self.peer_swarms[info_hash] if info_hash in self.peer_swarms else None

    def start(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((self.host, self.port))
        server.listen(5)
        print(f'Tracker running on {self.host}:{self.port}')

        thread = 1

        while True:
            conn, addr = server.accept()
            print("Connection trigger")
            thread = threading.Thread(target=self.handle_client, args=(conn, addr))
            thread.start()
            if keyboard.is_pressed('q'):
                break

        thread.join()


if __name__ == '__main__':
    tracker = Tracker('0.0.0.0', 6882)
#     tracker.start()
