import socket
import threading
import json
import os
import hashlib
import keyboard
import bencodepy
import random
import string
import select
import pickle
import math
import time
import bitarray

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from bittorrent_lib.torrent_file import TorrentFile
from collections import OrderedDict

HANDSHAKE_MSG_SIZE = 68
TCP_MESSAGE_SIZE = 4
TCP_MESSAGE_ID_SIZE = 1

CHOKE_ID = 0
UNCHOKE_ID = 1
INTEREST_ID = 2
NOT_INTEREST_ID = 3
HAVE_ID = 4
BITFIELD_ID = 5
REQUEST_ID = 6
PIECE_ID = 7
CANCEL = 8

class Peer:
    def __init__(self, listen_ip='127.0.0.1', listen_port=6883, sim_peer_id=1):
        self.is_running = True
        self.time_stamp = os.times()

        self.tracker_url = 'http://127.0.0.1:6882/announce'  # Default tracker url if file has not been created
        self.peer_id = self.generate_peer_id()
        self.listen_ip = listen_ip
        self.port = listen_port

        self.not_download_files = {}  # List to store file hashes and paths
        self.download_files = {}
        self.seeder_swarm = {}
        self.leecher_swarm = {}
        self.sim_peer_id = sim_peer_id

        # Start up tcp socket to start listen
        self.tcp_socket_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket_conn.bind((self.listen_ip, self.port))
        self.tcp_socket_conn.listen()

        self.downloading_queue_lock = threading.Lock()
        self.downloading_queue = []

        # Create torrent file if it's not exist and then announce to the tracker
        if os.listdir(os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'torrent_file')):  # Folder File is not empty
            for filename in os.listdir(os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'torrent_file')):
                raw_path = os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'Raw', filename.replace('.torrent', ''))
                torrent_path = os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'torrent_file', filename)
                # print('Source file: ', raw_path, ', Torrent path: ', torrent_path)
                file = TorrentFile(filename.replace('.torrent', ''), torrent_path, raw_path, self.tracker_url)
                print('file info hash: ', file.get_info_hash())
                if file.is_downloaded():
                    print('File name: ', filename, ' existed')
                    self.download_files[file.get_info_hash()] = file
                else:
                    self.not_download_files[file.get_info_hash()] = file
                self.announce_to_tracker(file, 'started')

        if os.listdir(os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'Raw')):
            for filename in os.listdir(os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'Raw')):
                if self.found_created_file(filename) is False:
                    raw_path = os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'Raw', filename)
                    torrent_path = os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'torrent_file', filename + '.torrent')
                    file = TorrentFile(filename.replace('.torrent', ''), torrent_path, raw_path, self.tracker_url)
                    print('file info hash: ', file.get_info_hash())
                    self.download_files[file.get_info_hash()] = file
                    self.announce_to_tracker(file, 'started')

    def announce_to_tracker_thread(self):
        while self.is_running:
            for file_key in list(self.download_files.keys()):
                self.announce_to_tracker(self.download_files[file_key], 'regular_check')
            for file_key in list(self.not_download_files.keys()):
                self.announce_to_tracker(self.not_download_files[file_key], 'regular_check')
            time.sleep(15)  # Every two minutes, the peer will update the list

    def announce_to_tracker(self, torrent_file: TorrentFile, event_type: str):
        try:
            with open(os.path.abspath(torrent_file.get_torrent_file_path()), 'rb') as f:
                data = f.read()

            url = bencodepy.decode(data)[b'announce'].decode('utf-8')
            data = bencodepy.decode(data)[b'info']
            info_hash = hashlib.sha1(bencodepy.encode(data)).digest()
            downloaded = 0 if not torrent_file.have_file() else torrent_file.get_file_size()
            remain_size = torrent_file.get_file_size() - downloaded
            para = {
                'info_hash': info_hash,
                'peer id': self.peer_id,
                'listen ip': self.listen_ip,
                'port': self.port,
                'event': event_type,
                'downloaded': downloaded,
                'left': remain_size
            }
            response = requests.get(url, params=para)
            response = json.loads(response.content.decode('utf-8'))
            if len(response) > 0:
                self.seeder_swarm[info_hash] = []
                self.leecher_swarm[info_hash] = []
                # print('response peers', response)
                for network_peer in response['Peers']:
                    if network_peer['is_seeder']:
                        self.seeder_swarm[info_hash].append(network_peer)
                        # print('peer id', network_peer['peer id'], ' has been added to seeder swarm')
                    else:
                        self.leecher_swarm[info_hash].append(network_peer)
                        # print('peer id', network_peer['peer id'], ' has been added to leecher swarm')

        except Exception as e:
            print('Error', e)

    def generate_peer_id(self):
        rand_num = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
        return '-PeerID-' + rand_num

    def select_peer(self, info_hash: str, max_peers=10):
        seeder_list = self.seeder_swarm.get(info_hash, [])
        leecher_list = self.leecher_swarm.get(info_hash, [])

        total_peers = len(seeder_list) + len(leecher_list)
        if total_peers < max_peers:
            max_peers = total_peers

        selected_peers = random.sample(seeder_list, min(len(seeder_list), max_peers))
        remaining_slots = max_peers - len(selected_peers)

        if remaining_slots > 0:
            selected_peers += random.sample(leecher_list, min(len(leecher_list), remaining_slots))

        return selected_peers

    def generate_handshake(self, info_hash_handshake: bytes):
        """
        :param peer_id: 20 bytes
        :param info_hash: 20 bytes
        :note: The handshake message size is always 68 bytes
        :return: handshake message with format <pstrlen     (1 byte):       19 for bitorrent>
                                               <pstr        (19 bytes):     "BitTorrent protocol">
                                               <reserved    (8 bytes):      all zeroes or feature flags>
                                               <info hash   (20 bytes):     info hash of torrent file>
                                               <peer id     (20 bytes):     id of target peer>
        """
        pstrlen = b'\x13'
        pstr = b'BitTorrent protocol'
        reserved = b'\x00'*8
        peer_id_handshake = self.peer_id.encode()
        return pstrlen + pstr + reserved + info_hash_handshake + peer_id_handshake

    def found_created_file(self, filename):
        for file in list(self.download_files.values()):
            if filename == file.get_raw_file_name():
                return True
        return False

    def ordered_to_dict(self, obj):
        if isinstance(obj, OrderedDict):
            return {self.decode_bytes(self.ordered_to_dict(k)): self.decode_bytes(self.ordered_to_dict(v)) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.ordered_to_dict(i) for i in obj]
        else:
            return obj

    def decode_bytes(self, obj):
        if isinstance(obj, bytes):
            try:
                return obj.decode('utf-8')
            except UnicodeDecodeError:
                return obj
        else:
            return obj

    def handle_peer_request(self):
        global stop_event
        inputs = [self.tcp_socket_conn]
        peer_connections = {}

        while not stop_event.is_set():
            readable, _, _ = select.select(inputs, [], [], 1)

            for sock in readable:
                if sock is self.tcp_socket_conn:
                    # Có kết nối mới
                    conn, addr = self.tcp_socket_conn.accept()
                    conn.setblocking(True)
                    inputs.append(conn)
                    peer_connections[conn] = {'handshake_done': False}
                else:
                    try:
                        if not peer_connections[sock]['handshake_done']:
                            print('Receive handshake')
                            handshake = sock.recv(HANDSHAKE_MSG_SIZE)
                            if len(handshake) >= HANDSHAKE_MSG_SIZE:
                                # Parse info_hash và peer_id từ handshake
                                info_hash = handshake[28:48]
                                handshake_peer_id = handshake[48:68]
                                handshake = handshake[:48] + self.peer_id.encode()
                                print(f'Handshake from {handshake_peer_id.decode()} with info_hash {info_hash}')
                                # Gửi lại handshake (giống như gương)
                                sock.sendall(handshake)
                                peer_connections[sock]['info_hash'] = info_hash
                                peer_connections[sock]['peer_id'] = handshake_peer_id
                                peer_connections[sock]['handshake_done'] = True
                                for file in list(self.download_files.values()):
                                    # print('peer connection info hash: ', peer_connections[sock]['info_hash'], '. file info hash: ', file.get_info_hash())
                                    if file.get_info_hash() == peer_connections[sock]['info_hash']:
                                        # print('found matching file')
                                        peer_connections[sock]['file'] = file

                        else:
                            # Sau handshake, xử lý các message bình thường như bitfield, request, v.v.
                            msg_len_bytes = sock.recv(4)
                            if msg_len_bytes:
                                msg_len = int.from_bytes(msg_len_bytes, byteorder='big')
                                msg_type = sock.recv(1)
                                if msg_type == b'\x05':  # bitfield
                                    bitfield = sock.recv(msg_len - TCP_MESSAGE_ID_SIZE)
                                    # print(f"Received bitfield {bitfield}, sending our bitfield back...")
                                    response_bitfield = self.generate_bitfield_msg(peer_connections[sock]['file'])
                                    # print('Bitfield wanna response: ', response_bitfield)
                                    sock.sendall(response_bitfield)

                                elif msg_type == b'\x02':  # interested
                                    print("Peer is interested.")
                                    sock.sendall(self.generate_is_choke_msg(False))  # unchoke
                                elif msg_type == b'\x06':  # request
                                    payload = sock.recv(msg_len - 1)
                                    index = int.from_bytes(payload[:4], byteorder='big')
                                    begin = int.from_bytes(payload[4:8], byteorder='big')
                                    length = int.from_bytes(payload[8:12], byteorder='big')

                                    info_hash = peer_connections[sock]['info_hash']
                                    if info_hash in self.download_files:
                                        # print('Search for files with info hash: ', info_hash, '. At file info hash: ', file.get_info_hash())
                                        # if file.get_info_hash() == info_hash:
                                        piece_data = self.download_files[info_hash].get_piece(index)
                                        # print('found matching piece')
                                        if piece_data is not None:
                                            # print('data of piece: ', piece_data)
                                            piece_msg = self.generate_piece_msg(index, begin, piece_data)
                                            sock.sendall(piece_msg)
                                            print(f'Sent piece {index} to peer ', peer_connections[sock]['peer_id'])
                                        continue
                    except Exception as e:
                        print(f"[SEEDER ERROR] Exception with peer {peer_connections.get(sock, {}).get('peer_id', 'unknown')}: {e}")
                        if sock in inputs:
                            inputs.remove(sock)
                        if sock in peer_connections:
                            del peer_connections[sock]
                        try:
                            sock.close()
                        except Exception as close_err:
                            print(f"[SEEDER ERROR] Failed to close socket: {close_err}")
            time.sleep(0.1)

    def main_thread(self):
        while not stop_event.is_set():
            if keyboard.is_pressed('r'):
                self.request_for_files()
            time.sleep(0.1)

    def request_for_files(self):
        print('Searching for not downloaded files: ', self.not_download_files)
        for file in list(self.not_download_files.values()):
            print('Download file: ', file.get_raw_file_name())
            start_time = time.time()
            self.announce_to_tracker(file, 'started')
            file_info_hash = file.get_info_hash()
            print('request info hash: ', file_info_hash)
            peer_list = self.select_peer(file_info_hash)

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [
                    executor.submit(self.request_for_file_thread, peer_to_request, file, file_info_hash)
                    for peer_to_request in peer_list
                ]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"Thread error: {e}")

            print('     Downloaded time: ', time.time() - start_time)
            self.announce_to_tracker(file, 'completed')
            file.merge_all_pieces()
            del self.not_download_files[file.get_info_hash()]
            self.download_files[file.get_info_hash()] = file

    def request_for_file_thread(self, peer_to_request: dict, file: TorrentFile, file_info_hash):
        conn = socket.create_connection((peer_to_request['listen ip'], peer_to_request['port'])) # Connect to target peer using its ip and port
        handshake_msg = self.generate_handshake(file_info_hash)
        conn.sendall(handshake_msg)
        conn.settimeout(1)
        try:
            handshake_msg_response = conn.recv(HANDSHAKE_MSG_SIZE)
        except socket.timeout:
            print('Connection to peer timed out. Skip to next peer')
        if not handshake_msg_response:  # If the peer is not having the file then it will close the connection and the response is None => Skip to next peer
            conn.close()
            return
        piece_list = self.handle_bitfield_flow_control(conn, file)
        error_code = self.send_interest_and_receive_unchoke(conn)
        if error_code != 0:  # Handle choke message received
            conn.close()
            return  # Skip to next peer

        piece_receive = {}
        while file.get_nb_of_not_downloaded_pieces() > 0:
            # self.downloading_queue_lock.acquire()
            is_valid = False
            piece = -1  # Dummy init
            with self.downloading_queue_lock:
                # print('Thread id: ', threading.get_ident(), '. Not download list: ', file.not_downloaded_pieces, '. Nb of piece in not download piece list: ', file.get_nb_of_not_downloaded_pieces())
                if file.get_nb_of_not_downloaded_pieces() > 1:
                    piece = random.randint(0, file.get_nb_of_not_downloaded_pieces() - 1)
                elif file.get_nb_of_not_downloaded_pieces() == 1:
                    piece = 0
                # print('Thread id: ', threading.get_ident(), '. Piece to check: ', piece)
                if piece != -1:
                    # print('Thread id: ', threading.get_ident(), 'Piece idx to request: ', piece)
                    try:
                        piece = file.not_downloaded_pieces[piece]
                    except IndexError:
                        print('Thread id: ', threading.get_ident(), 'Piece idx error to request: ', piece, '. Current not download pieces list: ', file.not_downloaded_pieces)

                    if piece not in self.downloading_queue:
                        self.downloading_queue.append(piece)
                        is_valid = True

            if is_valid:
                # print('Thread id: ', threading.get_ident(), 'Request piece ', piece)
                piece_receive, error_code = self.request_for_piece(piece, conn, file)
                # print('Piece received: ', piece_idx, '. With data: ', piece_receive[piece_idx])
                if error_code != 0:
                    print('Receive error')
                    continue
                file.insert_received_pieces(piece, piece_receive)
                with self.downloading_queue_lock:
                    self.downloading_queue.remove(piece)
        conn.close()

    def request_for_piece(self, request_piece_idx: int, conn, torrent_file: TorrentFile):
        """
        :note: This function is for request for pieces of not downloaded file
        :param torrent_file:
        :param piece_list:
        :return: 0: If all pieces are downloaded
        """
        print(f'\rDownload progress: {torrent_file.get_nb_of_pieces() - torrent_file.get_nb_of_not_downloaded_pieces()}/{torrent_file.get_nb_of_pieces()}', end='')
        request_msg = self.generate_request_msg(request_piece_idx, torrent_file.get_piece_length())
        conn.sendall(request_msg)  # Send request message for wanted piece

        conn.settimeout(1)  # Set timeout for receiving 1 second
        try:
            piece_len = int.from_bytes(conn.recv(TCP_MESSAGE_SIZE), 'big')
            message_type_id = int.from_bytes(conn.recv(TCP_MESSAGE_ID_SIZE), 'big')
            if message_type_id != PIECE_ID:  # If the message is not response message
                print('\nRequest message receive a message of wrong type (Not piece message) with message type: ', message_type_id)
                return b'', -1
            try:
                piece_index = int.from_bytes(conn.recv(4), 'big')
            except Exception as e:
                print('\nError at request for piece: ', e)
            try:
                piece_offset = int.from_bytes(conn.recv(4), 'big')
            except Exception as e:
                print('\nError at receive piece offset: ', e)
            remain_size = piece_len - TCP_MESSAGE_ID_SIZE - 4 - 4
            data = b''
        except socket.timeout:
            print('Connection suddenly closed when request for piece')
            return b'', -1

        while remain_size > 0:
            try:
                piece_chunk = conn.recv(remain_size)
            except MemoryError as e:
                print('\nMemory error with error: ', e, '. Remain size: ', remain_size)
            if piece_chunk is None:
                raise ValueError('\nConnection suddenly closed')
            # print('Piece chunk received: ', piece_chunk)
            data += piece_chunk
            # print('data received: ', data)
            remain_size -= len(piece_chunk)

        if len(data) == 0:
            print('len data = 0')
            return b'', -1
        # mark = self.process_bar(torrent_file, piece_receive)
        # print(f"\rDownload status:  [{'-' * mark + ' ' * (20 - mark)}]", end='')

        return data, 0


    def process_bar(self, file, piece_list: list):
        return (int(len(piece_list) / float(file.get_nb_of_pieces()) * 20))

    def handle_bitfield_flow_control(self, conn, torrent_file: TorrentFile) -> list[int]:
        piece_list = []
        bitfield_msg = self.generate_bitfield_msg(torrent_file)
        conn.sendall(bitfield_msg)
        bitfield_len = int.from_bytes(conn.recv(TCP_MESSAGE_SIZE), 'big')
        if bitfield_len is None:
            raise ValueError('Bitfield length is None')
        # print(f'Bitfield len: {bitfield_len}')
        message_type_id = int.from_bytes(conn.recv(TCP_MESSAGE_ID_SIZE), 'big')
        # print(f'Message type id: {message_type_id}')
        if message_type_id < 0 or message_type_id > 9:
            print('Error in flow control')
        bitfield = bitarray.bitarray()
        bitfield.frombytes(conn.recv(bitfield_len - TCP_MESSAGE_ID_SIZE))
        for idx in range(0, len(bitfield)):
            if bitfield[idx]:
                piece_list.append(idx)
        # print('peer downloaded list receive: ', piece_list)
        return piece_list

    def generate_bitfield_msg(self, torrent_file: TorrentFile):
        message_type = b'\x05'
        nb_of_pieces = torrent_file.get_nb_of_pieces()
        bitfield_msg = ''
        # print('Downloaded pieces list: ', torrent_file.get_downloaded_pieces_list())
        for piece_idx in range(nb_of_pieces):
            if piece_idx in torrent_file.get_downloaded_pieces_list():
                bitfield_msg += '1'
            else:
                bitfield_msg += '0'

        bitfield_len = torrent_file.get_nb_of_pieces() - len(bitfield_msg) + (8 - torrent_file.get_nb_of_pieces() % 8)

        # print(f'Nb of pieces: {torrent_file.get_nb_of_pieces()}, bitfield msg len: {bitfield_msg}, filler len: {torrent_file.get_nb_of_pieces()%8}')
        # print('Bitfield len', bitfield_len)
        bitfield_msg += '0' * bitfield_len

        # print('Bitfield msg: ', bitfield_msg)

        bitfield = bitarray.bitarray(bitfield_msg)
        bitfield_msg = bitfield.tobytes()
        message_len = (1 + len(bitfield_msg)).to_bytes(4, byteorder='big')
        return message_len + message_type + bitfield_msg

    def generate_is_interest_msg(self, is_interest: bool):
        message_type = b'\x02' if is_interest else b'\x03'
        message_len = len(message_type).to_bytes(4, byteorder='big')
        return message_len + message_type

    def generate_is_choke_msg(self, is_choke: bool):
        message_type = b'\x00' if is_choke else b'\x01'
        message_len = len(message_type).to_bytes(4, byteorder='big')
        return message_len + message_type

    def generate_request_msg(self, piece_index: int, piece_length: int):
        message_type = b'\x06'
        piece_index = piece_index.to_bytes(4, byteorder='big')
        begin_offset = b'\x00' * 4
        piece_length = piece_length.to_bytes(4, byteorder='big')
        message_len = (len(message_type) + len(piece_index) + len(begin_offset) + len(piece_length)).to_bytes(4, byteorder='big')

        return message_len + message_type + piece_index + begin_offset + piece_length

    def generate_piece_msg(self, piece_index: int, begin_offset: int, data: bytes):
        message_type_id = b'\x07'
        piece_index = piece_index.to_bytes(4, byteorder='big')
        begin_offset = begin_offset.to_bytes(4, byteorder='big')
        # if len(data) % 8 != 0:
        #     data += b'\x00' * (8 - len(data) % 8)
        # print('data len: ', len(data))
        message_len = (len(message_type_id) + len(piece_index) + len(begin_offset) + len(data)).to_bytes(4, byteorder='big')
        return message_len + message_type_id + piece_index + begin_offset + data

    def send_interest_and_receive_unchoke(self, conn):
        """
        :note:          This function is for send interest and receive unchoke message
        :return:        0: If receive unchoke message, 1: If receive choke message
        """
        interest_msg = self.generate_is_interest_msg(True)
        conn.sendall(interest_msg)
        conn.settimeout(0.5)
        try:
            message_len = int.from_bytes(conn.recv(TCP_MESSAGE_SIZE), 'big')
            if message_len != 1:  # Handle unexpected error like not a unchoke or choke message
                raise ValueError('Receive unexpected error, not correct choke / unchoke message length')
            message_type_id = int.from_bytes(conn.recv(TCP_MESSAGE_ID_SIZE), 'big')
            if message_type_id == CHOKE_ID:
                return 1
            if message_type_id != UNCHOKE_ID:
                raise ValueError('Request message receive a message of wrong type (Not choke message)')
        except socket.timeout:
            print('Connection suddenly closed when sending interest and wait for receive')

        # print('Received an unchoke message from peer')

        return 0

    def find_files_in_file_list(self, info_hash: str):
        for file_info_hash in list(self.download_files.keys()):
            if info_hash == file_info_hash:
                print('File found')


if __name__ == '__main__':
    stop_event = threading.Event()  # For ending thread

    peer_id = int(input('Enter Peer ID: '))
    port = int(input('Please enter port number: '))

    threads_pool = []
    peer = Peer(listen_ip='127.0.0.1', listen_port=port, sim_peer_id=peer_id)
    # threads_pool.append(threading.Thread(target=peer.announce_to_tracker_thread))
    threads_pool.append(threading.Thread(target=peer.handle_peer_request))
    threads_pool.append(threading.Thread(target=peer.main_thread))

    for thread in threads_pool:
        thread.start()
    while True:
        if keyboard.is_pressed('q'):
            stop_event.set()
            for thread in threads_pool:
                thread.join()
            break
