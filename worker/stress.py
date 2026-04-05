import multiprocessing
import time
import argparse

def worker():
    """A busy loop that maxes out a CPU core."""
    while True:
        _ = 1 * 1

def main():
    parser = argparse.ArgumentParser(description="A lightweight cross-platform alternative to stress-ng for Windows.")
    parser.add_argument('--cpu', type=int, default=multiprocessing.cpu_count(), help='Number of CPU cores to stress')
    parser.add_argument('--timeout', type=int, default=60, help='Timeout in seconds (default 60)')
    
    args = parser.parse_args()
    
    print(f"Stressing {args.cpu} cores for {args.timeout} seconds...")
    
    processes = []
    for _ in range(args.cpu):
        p = multiprocessing.Process(target=worker)
        p.daemon = True
        p.start()
        processes.append(p)
        
    try:
        time.sleep(args.timeout)
        print("\nTimeout reached. Stopping stress test.")
    except KeyboardInterrupt:
        print("\nInterrupted by user. Stopping stress test.")
    finally:
        for p in processes:
            p.terminate()
        print("Done.")

if __name__ == '__main__':
    main()
