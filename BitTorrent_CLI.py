import argparse
import shlex
from Peer import Peer
from Tracker import Tracker
from  bittorrent_lib.torrent_file import TorrentFile
import threading
import bencodepy
from collections import OrderedDict
import os

tracker = None
peer: list[Peer] = []
threads_pool = []

def find_all_torrent_files_name(id: int):
    path = os.path.join(os.path.curdir, 'Sim', str(id), 'File', 'torrent_file')
    if not os.path.exists(path):
        print('\033[33mError: No torrent file directory found for peer ', id)

    file_idx = 1
    file_found = False
    print('\033[32mTorrent files list of peer ', id)
    for file in os.listdir(path):
        if file.endswith('.torrent'):
            print(f'\t\033[0mFile {file_idx}: ', file)
            file_idx += 1
            file_found = True
            
    if not file_found:
        print('\033[31m\tNo torrent file found')

def find_torrent_file(path, raw_path, torrent_file_name):
    if os.path.exists(path):
        for filename in os.listdir(path):
            if filename == torrent_file_name:
                path = os.path.join(path, filename)
            # print('file name: ', filename.replace('.torrent', ''))
            # print ('path: ', path)
            # torrent_file = TorrentFile(filename.replace('.torrent', ''), path, raw_path)
            try:
                with open(path, 'rb') as f:
                    data = f.read()
                data = bencodepy.decode(data)
                data = ordered_to_dict(data)
                print('Torrent file content: ', data)
            except Exception as e:
                print('Exception while taking file size from torrent file', e)
            return 0
        print('\033[31mCannot find torrent file')
        return -1
    else:
        # print
        print('\033[31mError directory')
        
def ordered_to_dict(obj):
    if isinstance(obj, OrderedDict):
        return {decode_bytes(ordered_to_dict(k)): decode_bytes(ordered_to_dict(v)) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [ordered_to_dict(i) for i in obj]
    else:
        return obj
    
def decode_bytes(obj):
    if isinstance(obj, bytes):
        try:
            return obj.decode('utf-8')
        except UnicodeDecodeError:
            return obj
    else:
        return obj
        
def create_torrent(raw_file_name:str, sim_peer_id:int, tracker_url:str):
    if os.listdir(os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'Raw')):  # Search in the folder Raw
        for filename in os.listdir(os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'Raw')):  # Traverse all the files in the folder Raw
            if filename == raw_file_name:  # Check if the file name is the same as the one in the torrent file
                raw_path = os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'Raw', filename)
                torrent_path = os.path.join(os.path.curdir, 'Sim', str(sim_peer_id), 'File', 'torrent_file', filename + '.torrent')
                TorrentFile(filename, torrent_path, raw_path, tracker_url)

def handle_torrent_tracker(args):
    global tracker
    parser = argparse.ArgumentParser(prog="torrent-tracker")
    parser.add_argument('-p', "--port", default=6882, help='Port for the tracker to listen on (default: 6882)')
    parser.add_argument('-ip', "--ip", default='127.0.0.1', help='Torrent to listen ip. By default it will run on local using 127.0.0.1')
    try:
        parsed = parser.parse_args(args)
        tracker = Tracker(parsed.ip, parsed.port)
    except SystemExit:
        if '-h' not in args and '--help' not in args:
            print('\033[31mInvalid arguments for tracker create')
        pass

def handle_torrent_seed(args):
    global peer
    global threads_pool

    parser = argparse.ArgumentParser(prog="torrent-seed")
    parser.add_argument("-id", "--sim_id", type=int, default=-1, help="ID of peer for simulation")
    parser.add_argument("-ip", "--ip", default="127.0.0.1", help="Peer listening IP to use")
    parser.add_argument("-p", "--port", type=int, default=5001, help="Peer listening port to use")
    parser.add_argument("-f", "--file", required=True, help="Torrent file")
    parser.add_argument("-url", "--tracker_url", default='http://127.0.0.1:6882/announce', help="Traker url to listen on")
    try:
        parsed = parser.parse_args(args)
        # print(f"Seeding arguments: {parsed}")
        # print(f"Seeding {parsed.file} from {parsed.directory} on port {parsed.port}")
        # print('Seeding file to tracker: ', parsed.tracker_url)
        seeder = None
        # print('Peer list before: ', peer)
        for p in peer:
            ip, port = p.tcp_socket_conn.getsockname()
            # print(f"Peer {p.sim_id} is seeding on {ip}:{port}")
            if ip == parsed.ip and port == int(parsed.port):
                seeder = p
                break
        if seeder is None:
            seeder = Peer(str(parsed.ip), int(parsed.port), parsed.tracker_url)
            peer.append(seeder)
            threads_pool.append(threading.Thread(target=seeder.announce_to_tracker_thread))
            threads_pool.append(threading.Thread(target=seeder.handle_peer_request))
                
        error_code = seeder.join_network(parsed.sim_id, is_seeder=True, torrent_file_name=parsed.file)
        if error_code != 0:
            print('\033[31mSeeder does not have the given file')
            return

        for thread in threads_pool:
            if not thread.is_alive():
                thread.start()
        # print('Peer list after: ', peer)

    except SystemExit:
        pass

def handle_torrent_leave(args):
    global peer
    global threads_pool

    parser = argparse.ArgumentParser(prog="torrent-leave")
    
    if len(peer) > 0:
        for p in peer:
            # print(f"Stopping peer ", p)
            p.stop_event.set()
            p.leave_network()

    if len(threads_pool) > 0:
        for thread in threads_pool:
            if thread.is_alive():
                # print(f"Stopping thread ", thread)
                thread.join()
        threads_pool = []


def handle_torrent_leech(args):
    global peer
    global threads_pool
    
    socket_exist = False
    parser = argparse.ArgumentParser(prog="torrent-leech")
    parser.add_argument("-id", "--sim_id", default=-1, help="Id of simulation peer")
    parser.add_argument("-ip", "--ip", default='127.0.0.1', help="Peer listening IP to use")
    parser.add_argument("-p", "--port", type=int, default=5001, help="Peer listening port to use")
    parser.add_argument("-f", "--file", required=True, help="Torrent file")
    parser.add_argument("-url", "--tracker_url", default='http://127.0.0.1:6882/announce', help="Tracker url to listen on")
    try:
        parsed = parser.parse_args(args)
        leecher = None
        for p in peer:
            ip, port = p.tcp_socket_conn.getsockname()
            # print(f"Peer {p.sim_id} is seeding on {ip}:{port}")
            if ip == parsed.ip and port == int(parsed.port):
                leecher = p
                socket_exist = True
                break
        if leecher is None:
            leecher = Peer(parsed.ip, parsed.port, parsed.tracker_url)
            peer.append(leecher)
        leecher.join_network(parsed.sim_id, is_seeder=False, torrent_file_name=parsed.file)
        thread_leech = threading.Thread(target=leecher.leech_files, args=(parsed.file,))
        threads_pool.append(thread_leech)
        threads_pool[-1].start()
    except SystemExit:
        pass
    finally:
        threads_pool.remove(thread_leech)
        if not socket_exist:
            threads_pool.append(threading.Thread(target=leecher.announce_to_tracker_thread))
            threads_pool.append(threading.Thread(target=leecher.handle_peer_request))
        # threads_pool.append(threading.Thread(target=peer.main_thread))

        for thread in threads_pool:
            if not thread.is_alive():
                thread.start()

def handle_torrent_daemon(args):
    parser = argparse.ArgumentParser(prog="torrent-daemon")
    parser.add_argument("command", choices=["start", "stop", "status"], help="Control command")
    try:
        parsed = parser.parse_args(args)
        print(f"Daemon command: {parsed.command}")
    except SystemExit:
        pass

def handle_torrent_fetch(args):
    parser = argparse.ArgumentParser(prog="torrent-fetch")
    parser.add_argument("-id", "--sim_id", default=-1, help="Id of simulation peer")
    try:
        parsed = parser.parse_args(args)  # No args expected
        sim_id = []
        
        if parsed.sim_id == -1:
            for file in os.listdir(os.path.join(os.path.curdir, 'Sim')):
                sim_id.append(int(file))
        else:
            sim_id.append(parsed.sim_id)
        for id in sim_id:
            find_all_torrent_files_name(id)
    except SystemExit:
        pass

def handle_torrent_show(args):
    parser = argparse.ArgumentParser(prog="torrent-show")
    parser.add_argument("-f", "--file", help="Torrent file to show")
    parser.add_argument("-id", "--sim_id", help="Id of simulation peer")
    try:
        parsed = parser.parse_args(args)
        path = os.path.join(os.path.curdir, 'Sim', str(parsed.sim_id), 'File', 'torrent_file')
        raw_path = os.path.join(os.path.curdir, 'Sim', str(parsed.sim_id), 'File', 'Raw')
        find_torrent_file(path, raw_path, parsed.file)
        # print(f"Showing info for torrent: {parsed.torrent}")
    except SystemExit:
        pass

def handle_torrent_create(args):
    parser = argparse.ArgumentParser(prog="torrent-create")
    parser.add_argument("-id", "--sim_id", required=True, help="Id of simulation peer")
    parser.add_argument("-f", "--file", required=True, help="File")
    parser.add_argument("-url", "--tracker_url", default='http://127.0.0.1:6882/announce', help="Tracker url to listen on")
    try:
        parsed = parser.parse_args(args)
        create_torrent(parsed.file, parsed.sim_id, parsed.tracker_url)
    except SystemExit:
        pass

# Command dispatcher
command_handlers = {
    "torrent-seed": handle_torrent_seed,
    "torrent-leech": handle_torrent_leech,
    "torrent-daemon": handle_torrent_daemon,
    "torrent-fetch": handle_torrent_fetch,
    "torrent-show": handle_torrent_show,
    "torrent-create": handle_torrent_create,
    "torrent-tracker": handle_torrent_tracker,
    "torrent-leave": handle_torrent_leave,
}

def safe_shutdown():
    global threads_pool
    if len(threads_pool):
        for thread in threads_pool:
            if thread.is_alive():
                thread.join()

def main():
    print("BitTorrent Interactive CLI. Type 'exit' to quit.")
    while True:
        try:
            raw_input = input("\033[0m>>> ").strip()
            if raw_input.lower() in {"exit", "quit"}:
                if len(peer) > 0:
                    for p in peer:
                        # print(f"Stopping peer ", p)
                        p.stop_event.set()
                        p.leave_network()

                if len(threads_pool) > 0:
                    for thread in threads_pool:
                        if thread.is_alive():
                            # print(f"Stopping thread ", thread)
                            thread.join()
                break

            tokens = shlex.split(raw_input)
            if not tokens:
                continue

            cmd, *cmd_args = tokens
            handler = command_handlers.get(cmd)

            if handler:
                handler(cmd_args)
            else:
                print(f"\033[31mUnknown command: {cmd}")
        except KeyboardInterrupt:
            print("\n\033[0mExiting.")
            break


if __name__ == "__main__":
    main()
