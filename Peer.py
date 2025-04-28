import socket
import threading
import json
import os
import hashlib
import bencodepy
import random
import string
import select
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
    def __init__(self, listen_ip='127.0.0.1', listen_port=6883, tracker_url='http://127.0.0.1:6882/announce'):
        self.is_running = True
        self.time_stamp = os.times()

        self.tracker_url = tracker_url  # Default tracker url if file has not been created
        self.peer_id = self.generate_peer_id()
        self.listen_ip = listen_ip
        self.port = listen_port

        self.not_download_files = {}  # List to store file hashes and paths
        self.download_files = {}
        self.seeder_swarm = {}
        self.leecher_swarm = {}
        self.sim_peer_id = -1

        # Start up tcp socket to start listen
        self.tcp_socket_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket_conn.bind((self.listen_ip, self.port))
        self.tcp_socket_conn.listen()

        self.downloading_queue_lock = threading.Lock()
        self.downloading_queue = []
        self.stop_event = threading.Event() 

    def join_network(self, sim_peer_id=-1, is_seeder=False, torrent_file_name='.torrent'):
        self.sim_peer_id = sim_peer_id

        # Create torrent file if it's not exist and then announce to the tracker
        if os.listdir(os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'torrent_file')):  # Torrent Folder File is not empty
            for filename in os.listdir(os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'torrent_file')):  # Traverse all the files in the folder torrent_file
                if filename == '.torrent' or filename == torrent_file_name:  # Check if the file is request torrent file
                    raw_path = os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'Raw', filename.replace('.torrent', ''))
                    torrent_path = os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'torrent_file', filename)

                    file = TorrentFile(filename.replace('.torrent', ''), torrent_path, raw_path, self.tracker_url)
                    if file.is_downloaded():
                        if is_seeder is False:
                            return -2
                        self.download_files[file.get_info_hash()] = file
                    else:
                        if is_seeder is True:
                            return -1
                        self.not_download_files[file.get_info_hash()] = file
                    self.announce_to_tracker(file, 'started')

        return 0

    def announce_to_tracker_thread(self):
        while self.is_running and not self.stop_event.is_set():
            for file_key in list(self.download_files.keys()):
                self.announce_to_tracker(self.download_files[file_key], 'regular_check')
            for file_key in list(self.not_download_files.keys()):
                self.announce_to_tracker(self.not_download_files[file_key], 'regular_check')
            time.sleep(15)  # Every two minutes, the peer will update the list


    def leave_network(self):
        for info_hash in list(self.download_files.keys()):
            self.announce_to_tracker(self.download_files[info_hash], 'stopped')
        
        for info_hash in list(self.not_download_files.keys()):
            self.announce_to_tracker(self.not_download_files[info_hash], 'stopped')
        self.tcp_socket_conn.close()

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
            if event_type != 'stopped':
                if len(response) > 0:
                    self.seeder_swarm[info_hash] = []
                    self.leecher_swarm[info_hash] = []
                    
                    for network_peer in response['Peers']:
                        if network_peer['is_seeder']:
                            self.seeder_swarm[info_hash].append(network_peer)
                        else:
                            self.leecher_swarm[info_hash].append(network_peer)

        except Exception as e:
            print('\033[0mError at announce to tracker', e, ' with event type: ', event_type, ' and torrent file: ', torrent_file.get_torrent_file_name())

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
        inputs = [self.tcp_socket_conn]
        peer_connections = {}

        while not self.stop_event.is_set():
            readable, _, _ = select.select(inputs, [], [], 1)

            for sock in readable:
                if sock is self.tcp_socket_conn:
                    # Có kết nối mới
                    if self.stop_event.is_set():
                        break
                    conn, addr = self.tcp_socket_conn.accept()
                    conn.setblocking(True)
                    inputs.append(conn)
                    peer_connections[conn] = {'handshake_done': False}
                else:
                    try:
                        if not peer_connections[sock]['handshake_done']:
                            handshake = sock.recv(HANDSHAKE_MSG_SIZE)
                            if len(handshake) >= HANDSHAKE_MSG_SIZE:
                                # Parse info_hash và peer_id từ handshake
                                info_hash = handshake[28:48]
                                handshake_peer_id = handshake[48:68]
                                handshake = handshake[:48] + self.peer_id.encode()
                                # Gửi lại handshake (giống như gương)
                                sock.sendall(handshake)
                                peer_connections[sock]['info_hash'] = info_hash
                                peer_connections[sock]['peer_id'] = handshake_peer_id
                                peer_connections[sock]['handshake_done'] = True
                                for file in list(self.download_files.values()):
                                    if file.get_info_hash() == peer_connections[sock]['info_hash']:
                                        peer_connections[sock]['file'] = file

                        else:
                            # Sau handshake, xử lý các message bình thường như bitfield, request, v.v.
                            msg_len_bytes = sock.recv(4)
                            if msg_len_bytes:
                                msg_len = int.from_bytes(msg_len_bytes, byteorder='big')
                                msg_type = sock.recv(1)
                                if msg_type == b'\x05':  # bitfield
                                    bitfield = sock.recv(msg_len - TCP_MESSAGE_ID_SIZE)
                                    response_bitfield = self.generate_bitfield_msg(peer_connections[sock]['file'])
                                    sock.sendall(response_bitfield)

                                elif msg_type == b'\x02':  # interested
                                    print("Peer is interested.")
                                    sock.sendall(self.generate_is_choke_msg(False))  # unchoke
                                elif msg_type == b'\x06':  # request
                                    payload = sock.recv(msg_len - 1)
                                    index = int.from_bytes(payload[:4], byteorder='big')
                                    begin = int.from_bytes(payload[4:8], byteorder='big')

                                    info_hash = peer_connections[sock]['info_hash']
                                    if info_hash in self.download_files:
                                        piece_data = self.download_files[info_hash].get_piece(index)
                                        if piece_data is not None:
                                            piece_msg = self.generate_piece_msg(index, begin, piece_data)
                                            sock.sendall(piece_msg)
                                            # print(f'Sent piece {index} to peer ', peer_connections[sock]['peer_id'])
                                        continue
                    except Exception as e:
                        print(f"\033[0m[SEEDER ERROR] Exception with peer {peer_connections.get(sock, {}).get('peer_id', 'unknown')}: {e}")
                        if sock in inputs:
                            inputs.remove(sock)
                        if sock in peer_connections:
                            del peer_connections[sock]
                        try:
                            sock.close()
                        except Exception as close_err:
                            print(f"\033[0m[SEEDER ERROR] Failed to close socket: {close_err}")
            time.sleep(0.1)

    def request_for_files(self):
        for file in list(self.not_download_files.values()):
            print('\033[0mDownload file: ', file.get_raw_file_name())
            start_time = time.time()
            self.announce_to_tracker(file, 'started')
            file_info_hash = file.get_info_hash()
            print('\033[0mrequest info hash: ', file_info_hash)
            peer_list = self.select_peer(file_info_hash)

            retry = True
            while retry:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [
                        executor.submit(self.request_for_file_thread, peer_to_request, file, file_info_hash)
                        for peer_to_request in peer_list
                    ]
                    for future in as_completed(futures):
                        try:
                            error_code = future.result()
                            if error_code == -2:
                                retry = True
                            else:
                                retry = False

                        except Exception as e:
                            print(f"Thread error: {e}")

            print('\033[0m     Downloaded time: ', time.time() - start_time)
            self.announce_to_tracker(file, 'completed')
            file.merge_all_pieces()
            del self.not_download_files[file.get_info_hash()]
            self.download_files[file.get_info_hash()] = file
            
    def leech_files(self, torrent_file_name='.torrent'):
        error_code = -1
        for file in list(self.not_download_files.values()):
            if file.get_torrent_file_name() != torrent_file_name:
                continue
            print('\033[33mPrepare to download file: ', file.get_raw_file_name())
            seeder_list = []
            seeder_lock = threading.Lock()
            start_time = time.time()
            print('Announce to tracker with url: ', self.tracker_url)
            self.announce_to_tracker(file, 'started')
            file_info_hash = file.get_info_hash()
            peer_list = self.select_peer(file_info_hash)
            retry = True
            while retry:
                with ThreadPoolExecutor(max_workers=20) as executor:
                    futures = [
                        executor.submit(self.request_for_file_thread, peer_to_request, file, file_info_hash, seeder_list, seeder_lock)
                        for peer_to_request in peer_list
                    ]
                    for future in as_completed(futures):
                        try:
                            error_code = future.result()
                            if error_code == -2:
                                retry = True
                            else:
                                retry = False

                        except Exception as e:
                            print(f"\033[0mThread error: {e}")
                            
            if file.get_nb_of_not_downloaded_pieces() == file.get_nb_of_pieces():
                print('\033[0mFile is not downloaded any pieces')
                if os.path.exists(file.get_raw_file_path()):
                    os.remove(file.get_raw_file_path())
                if os.path.exists(file.get_torrent_file_path()+'.resume'):
                    os.remove(file.get_torrent_file_path()+'.resume')
            
            file.merge_all_pieces()
            print('\033[0m     Downloaded time: ', time.time() - start_time)
            if file.have_file() is True:
                self.announce_to_tracker(file, 'completed')
                del self.not_download_files[file.get_info_hash()]
                self.download_files[file.get_info_hash()] = file
            error_code = 0
        return error_code

    def request_for_file_thread(self, peer_to_request: dict, file: TorrentFile, file_info_hash, seeder_list: list, seeder_lock: threading.Lock):
        conn = socket.create_connection((peer_to_request['listen ip'], peer_to_request['port'])) # Connect to target peer using its ip and port
        handshake_msg = self.generate_handshake(file_info_hash)
        conn.sendall(handshake_msg)
        conn.settimeout(2)
        try:
            handshake_msg_response = conn.recv(HANDSHAKE_MSG_SIZE)
        except socket.timeout:
            print('\033[0mConnection to peer timed out. Skip to next peer')
        if not handshake_msg_response:  # If the peer is not having the file then it will close the connection and the response is None => Skip to next peer
            conn.close()
            return 0
        piece_list = self.handle_bitfield_flow_control(conn, file)
        error_code = self.send_interest_and_receive_unchoke(conn)
        if error_code != 0:  # Handle choke message received
            conn.close()
            return 0  # Skip to next peer

        while file.get_nb_of_not_downloaded_pieces() > 0:
            is_valid = False
            piece = -1  # Dummy init
            with self.downloading_queue_lock:
                if file.get_nb_of_not_downloaded_pieces() > 1:
                    piece = random.randint(0, file.get_nb_of_not_downloaded_pieces() - 1)
                elif file.get_nb_of_not_downloaded_pieces() == 1:
                    piece = 0
                if piece != -1:
                    try:
                        piece = file.not_downloaded_pieces[piece]
                    except IndexError:
                        print('\033[0mThread id: ', threading.get_ident(), 'Piece idx error to request: ', piece, '. Current not download pieces list: ', file.not_downloaded_pieces)

                    if piece not in self.downloading_queue:
                        self.downloading_queue.append(piece)
                        is_valid = True

            if is_valid:
                request_retry = 3
                while request_retry > 0:
                    piece_receive, error_code = self.request_for_piece(piece, conn, file, seeder_list)
                    if error_code != 0 or not file.check_piece_integrity(piece, piece_receive):
                        print('\033[0mReceive error')
                        request_retry -= 1
                        if request_retry == 0:
                            with self.downloading_queue_lock:
                                self.downloading_queue.remove(piece)
                            conn.close()
                            return -2
                    else:
                        file.insert_received_pieces(piece, piece_receive)
                        if peer_to_request['peer id'] not in seeder_list:
                            with seeder_lock:
                                seeder_list.append(peer_to_request['peer id'])
                        with self.downloading_queue_lock:
                            self.downloading_queue.remove(piece)
                        print(f'\r\033[0mDownload progress: {file.get_nb_of_downloaded_pieces()}/{file.get_nb_of_pieces()} from ', len(seeder_list), ' peers', end='')
                        break
        conn.close()
        return 0

    def request_for_piece(self, request_piece_idx: int, conn, torrent_file: TorrentFile, seeder_list: list):
        """
        :note: This function is for request for pieces of not downloaded file
        :param torrent_file:
        :param piece_list:
        :return: 0: If all pieces are downloaded
        """
        request_msg = self.generate_request_msg(request_piece_idx, torrent_file.get_piece_length())
        conn.sendall(request_msg)  # Send request message for wanted piece

        conn.settimeout(1)  # Set timeout for receiving 1 second
        try:
            piece_len = int.from_bytes(conn.recv(TCP_MESSAGE_SIZE), 'big')
            message_type_id = int.from_bytes(conn.recv(TCP_MESSAGE_ID_SIZE), 'big')
            if message_type_id != PIECE_ID:  # If the message is not response message
                print('\n\033[0mRequest message receive a message of wrong type (Not piece message) with message type: ', message_type_id)
                return b'', -1
            try:
                piece_index = int.from_bytes(conn.recv(4), 'big')
            except Exception as e:
                print('\n\033[0mError at request for piece: ', e)
            try:
                piece_offset = int.from_bytes(conn.recv(4), 'big')
            except Exception as e:
                print('\n\033[0mError at receive piece offset: ', e)
            remain_size = piece_len - TCP_MESSAGE_ID_SIZE - 4 - 4
            data = b''
        except socket.timeout:
            print('\033[0mConnection suddenly closed when request for piece')
            return b'', -1

        while remain_size > 0:
            try:
                piece_chunk = conn.recv(remain_size)
            except MemoryError as e:
                print('\n\033[0mMemory error with error: ', e, '. Remain size: ', remain_size)
            if piece_chunk is None:
                raise ValueError('\n\033[0mConnection suddenly closed')
            
            data += piece_chunk
            remain_size -= len(piece_chunk)

        if len(data) == 0:
            print('\033[0mlen data = 0')
            return b'', -1

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
        message_type_id = int.from_bytes(conn.recv(TCP_MESSAGE_ID_SIZE), 'big')
        if message_type_id < 0 or message_type_id > 9:
            print('\033[0mError in flow control')
        bitfield = bitarray.bitarray()
        bitfield.frombytes(conn.recv(bitfield_len - TCP_MESSAGE_ID_SIZE))
        for idx in range(0, len(bitfield)):
            if bitfield[idx]:
                piece_list.append(idx)

        return piece_list

    def generate_bitfield_msg(self, torrent_file: TorrentFile):
        message_type = b'\x05'
        nb_of_pieces = torrent_file.get_nb_of_pieces()
        bitfield_msg = ''
        for piece_idx in range(nb_of_pieces):
            if piece_idx in torrent_file.get_downloaded_pieces_list():
                bitfield_msg += '1'
            else:
                bitfield_msg += '0'

        bitfield_len = torrent_file.get_nb_of_pieces() - len(bitfield_msg) + (8 - torrent_file.get_nb_of_pieces() % 8)

        bitfield_msg += '0' * bitfield_len

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
            print('\033[0mConnection suddenly closed when sending interest and wait for receive')

        return 0
    