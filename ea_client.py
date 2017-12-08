import random
import sys
import threading
from fl_client import FederatedClient
from fl_server import obj_to_pickle_string, pickle_string_to_obj
from ea_server import print_request
import datasource


class ElasticAveragingClient(FederatedClient):
    def __init__(self, server_host, server_port, datasource):
        # probability to synchronize. Note: here epoch_per_round ~ 1/p
        self.p = None
        self.e = None   # weight for elasiticity term
        self.model_lock = threading.Lock()

        super(ElasticAveragingClient, self).__init__(server_host, server_port, datasource)

    # register socket handles
    def register_handles(self):
        super(ElasticAveragingClient, self).register_handles()

        def on_server_send_weights(*args):
            req = args[0]
            print_request('on_server_send_weights', req)

            global_w = pickle_string_to_obj(req['weights'])
            with self.model_lock:
                local_w = self.local_model.get_weights()
                diff = [self.e * (w-gw) for w,gw in zip(local_w, global_w)]
                self.local_model.set_weights([w-d for w,d in zip(local_w, diff)])

            self.send_weights(local_w)

        ## register handle
        self.sio.on('server_send_weights', on_server_send_weights)


    def on_init(self, *args):
        print_request('EA on_init', args[0])
        super(ElasticAveragingClient, self).on_init(*args)
        model_config = args[0]
        self.p = model_config["p"]
        self.e = model_config["e"]

        def train():
            while True:
                if random.random() < self.p:
                    self.request_weights()
                with self.model_lock:
                    print('train')
                    self.local_model.train_one_round()

        threading.Thread(target = train).start()

    def request_weights(self):
        self.sio.emit('client_request_weights')

    def send_weights(self, weights):
        self.sio.emit('client_send_weights', {
            'weights': obj_to_pickle_string(weights),
            'train_size': self.local_model.x_train.shape[0], # assume size won't change
            })


if __name__ == "__main__":
    port = sys.argv[1]
    c = ElasticAveragingClient("127.0.0.1", int(port), datasource.Mnist)