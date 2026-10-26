from app import server


def test_server_listen_backlog_takes_a_burst_of_pollers():
    assert issubclass(server.Server, server.ThreadingHTTPServer)
    assert server.Server.request_queue_size >= 64
    assert server.Server.daemon_threads
