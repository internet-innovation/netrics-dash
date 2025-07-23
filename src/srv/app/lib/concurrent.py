import concurrent.futures
import threading


def parallel(*funcs, max_workers=None):
    current_thread = threading.current_thread()

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers,
                                               thread_name_prefix=current_thread.name) as executor:
        futures = [executor.submit(func) for func in funcs]

        concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_EXCEPTION)

        # check for doneness in case of early exception
        return [future.result() for future in futures if future.done()]
