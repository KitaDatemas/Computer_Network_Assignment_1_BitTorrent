import os
import bencodepy
import hashlib
from collections import OrderedDict

class TorrentFile:
    def __init__(self, filename: str, destination_dir: str = '', src_file: str = '', tracker_url: str = 'http://127.0.0.1:5000/announce') -> None:
        # if not os.path.exists(src_file) or not os.path.exists(destination_dir):
        #     print('Error file path')

        # print(os.path.join(destination_dir))
        self.file_name = filename
        self.file_dir = destination_dir
        self.raw_file_dir = src_file
        self.piece_length = 2**19  # 512 KB

        self.downloaded_pieces = []
        self.pieces_data = {}

        if os.path.exists(src_file):  # Create a new file if that torrent file not exist
            self.torrent_file_dir = destination_dir

            self.file_frame = {}  # Dummy init
            self.create_torrent_file(src_file, tracker_url)
            self.magnet_text = self.get_magnet_text()

        with open(destination_dir, 'rb') as f:
            data = f.read()
            data = bencodepy.decode(data)
            data = self.ordered_to_dict(data)
            # print('data after decode: ', data)
            self.info_hash = hashlib.sha1(bencodepy.encode(data['info'])).digest()

        self.not_downloaded_pieces = range(len(self.downloaded_pieces), self.get_nb_of_pieces())

    def create_torrent_file(self, src_file: str, tracker_url: str = 'http://127.0.0.1:5000/announce'):
        # print('Create torrent file')
        self.file_frame = {
            'announce': tracker_url,
            'info': {
                'name': self.file_name,
                'length': os.path.getsize(src_file),
                'piece length': self.piece_length,
                'pieces': self.generate_pieces(2**20)
            }
        }
        with open(self.torrent_file_dir, 'wb') as torrent_file:
            torrent_file.write(bencodepy.encode(self.file_frame))

        self.info_hash = hashlib.sha1(bencodepy.encode(self.file_frame['info'])).digest()

    def get_raw_file_name(self):
        return self.file_name

    def get_torrent_file_name(self):
        return self.file_name + '.torrent'

    def get_raw_file_path(self):
        return self.raw_file_dir

    def get_torrent_file_path(self):
        return self.file_dir

    def have_file(self):
        return os.path.exists(os.path.abspath(self.raw_file_dir))

    def get_file_size(self):
        # try:
            # with open(self.get_torrent_file_path(), 'rb') as torrent_file:
            #     data = torrent_file.read()
            #
            # return int(bencodepy.decode(data)[b'info'][b'length'])
            #
        return self.get_torrent_content()['info']['length']
        # except Exception as e:
        #     print('Exception while taking file size from torrent file', e)

    def encode_file_SHA1(self):
        data_hashed = hashlib.sha1()
        with open(self.raw_file_dir, 'rb') as f:
            while chunk := f.read(1024):
                data_hashed.update(chunk)

        return data_hashed.hexdigest()

    def have_piece(self, piece: int):
        return piece in self.downloaded_pieces

    def get_info_hash(self):
        return self.info_hash

    def compare_info_hash(self, info_hash):
        return self.info_hash == info_hash

    def get_magnet_text(self):
        return 'magnet:?xt=urn:btih:' + self.get_info_hash().hex() + '&dn=' + 'Tracker' + '&tr=' + self.file_frame['announce']

    def generate_pieces(self, piece_length):
        pieces = b''
        piece_index = 0
        with open(self.raw_file_dir, 'rb') as f:
            while True:
                piece = f.read(piece_length)
                self.pieces_data[piece_index] = piece
                if not piece:
                    break
                pieces += hashlib.sha1(piece).digest()
                self.downloaded_pieces.append(piece_index)
                piece_index += 1
        return pieces

    def insert_received_pieces(self, piece_index: int, pieces_data: bytes):
        """
        :param piece_index:
        :param pieces_data:
        :note:      This function is for peer that at initial not a seeder, when it receives a file's piece it must save in order to quickly get the pieces
        """
        # print('Wanted to insert piece: ', piece_index, '. With data: ', pieces_data)
        if piece_index not in self.downloaded_pieces:
            # print('Insert piece', piece_index)
            self.pieces_data[piece_index] = pieces_data
            self.downloaded_pieces.append(piece_index)

    def get_torrent_content(self):
        try:
            with open(self.get_torrent_file_path(), 'rb') as f:
                data = f.read()
            data = bencodepy.decode(data)
            data = self.ordered_to_dict(data)
            return data

        except Exception as e:
            print('Exception while taking file size from torrent file', e)

    def get_nb_of_pieces(self):
        data = self.get_torrent_content()
        pieces = data['info']['pieces']
        return len(pieces) // 20

    def get_downloaded_pieces_list(self):
        return self.downloaded_pieces

    def decode_bytes(self, obj):
        if isinstance(obj, bytes):
            try:
                return obj.decode('utf-8')
            except UnicodeDecodeError:
                return obj
        else:
            return obj

    def ordered_to_dict(self, obj):
        if isinstance(obj, OrderedDict):
            return {self.decode_bytes(self.ordered_to_dict(k)): self.decode_bytes(self.ordered_to_dict(v)) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.ordered_to_dict(i) for i in obj]
        else:
            return obj

    def get_piece_length(self):
        return self.piece_length

    def get_piece(self, piece_index: int):
        if piece_index < 0 or piece_index >= self.get_nb_of_pieces():
            return None
        if piece_index not in list(self.pieces_data.keys()):
            return None
        return self.pieces_data[piece_index]

    def merge_all_pieces(self):
        # print('Downloaded pieces: ', self.downloaded_pieces, '. Number of pieces to be able to merge: ', self.get_nb_of_pieces())
        if len(self.downloaded_pieces) != self.get_nb_of_pieces():
            print('Warning: File is not downloaded enough pieces, so cannot merge')
            return

        with open(self.raw_file_dir, 'wb') as file:
            for piece_idx in self.downloaded_pieces:
                file.write(self.pieces_data[piece_idx])

        print('Save successfully')
