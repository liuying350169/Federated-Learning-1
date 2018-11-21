import numpy as np
import keras
import random
import time
import json
import pickle
import codecs
from keras.models import model_from_json
from socketIO_client import SocketIO, LoggingNamespace
from fl_server import obj_to_pickle_string, pickle_string_to_obj

import datasource
import threading

class LocalModel(object):
    def __init__(self, model_config, data_collected):
        # model_config:
            # 'model': self.global_model.model.to_json(),
            # 'model_id'
            # 'min_train_size'
            # 'data_split': (0.6, 0.3, 0.1), # train, test, valid
            # 'epoch_per_round'
            # 'batch_size'
        self.model_config = model_config

        self.model = model_from_json(model_config['model_json'])
        # the weights will be initialized on first pull from server

        self.model.compile(loss=keras.losses.categorical_crossentropy,
              optimizer=keras.optimizers.Adadelta(),
              metrics=['accuracy'])

        train_data, test_data, valid_data = data_collected
        self.x_train = np.array([tup[0] for tup in train_data])
        self.y_train = np.array([tup[1] for tup in train_data])
        self.x_test = np.array([tup[0] for tup in test_data])
        self.y_test = np.array([tup[1] for tup in test_data])
        self.x_valid = np.array([tup[0] for tup in valid_data])
        self.y_valid = np.array([tup[1] for tup in valid_data])

    def get_weights(self):
        return self.model.get_weights()

    def set_weights(self, new_weights):
        self.model.set_weights(new_weights)

    # return final weights, train loss, train accuracy
    def train_one_round(self):
        
        time_start_train_one_round = time.time()
        print("------------------------------------------------time_start_train_one_round: ", time_start_train_one_round-time_start)
        #fo.write("time_start_train_one_round:    " + str(time_start_train_one_round) + "\n")
        
        self.model.compile(loss=keras.losses.categorical_crossentropy,
              optimizer=keras.optimizers.Adadelta(),
              metrics=['accuracy'])

        self.model.fit(self.x_train, self.y_train,
                  epochs=self.model_config['epoch_per_round'],
                  batch_size=self.model_config['batch_size'],
                  verbose=1,
                  validation_data=(self.x_valid, self.y_valid))

        score = self.model.evaluate(self.x_train, self.y_train, verbose=0)
        print('Train loss:', score[0])
        print('Train accuracy:', score[1])
        
        time_finish_train_one_round = time.time()
        print("------------------------------------------------time_finish_train_one_round: ", time_finish_train_one_round-time_start)
        #fo.write("time_finish_train_one_round:    " + str(time_finish_train_one_round) + "\n")
        
        return self.model.get_weights(), score[0], score[1]

    def validate(self):
        score = self.model.evaluate(self.x_valid, self.y_valid, verbose=0)
        print('Validate loss:', score[0])
        print('Validate accuracy:', score[1])
        return score

    def evaluate(self):
        score = self.model.evaluate(self.x_test, self.y_test, verbose=0)
        print('Test loss:', score[0])
        print('Test accuracy:', score[1])
        return score


# A federated client is a process that can go to sleep / wake up intermittently
# it learns the global model by communication with the server;
# it contributes to the global model by sending its local gradients.

class FederatedClient(object):
    MAX_DATASET_SIZE_KEPT = 1200

    def __init__(self, server_host, server_port, datasource):
        self.local_model = None
        self.datasource = datasource()

        self.sio = SocketIO(server_host, server_port, LoggingNamespace)
        self.register_handles()
        print("sent wakeup")
        self.sio.emit('client_wake_up')
        self.sio.wait()

    
    ########## Socket Event Handler ##########
    def on_init(self, *args):
        model_config = args[0]
        print('on init', model_config)
        print('preparing local data based on server model_config')
        # ([(Xi, Yi)], [], []) = train, test, valid
        fake_data, my_class_distr = self.datasource.fake_non_iid_data(
            min_train=model_config['min_train_size'],
            max_train=FederatedClient.MAX_DATASET_SIZE_KEPT,
            data_split=model_config['data_split']
        )
        
        time_fake_data_done = time.time()
        print("------------------------------------------------time_fake_data_done: ", time_fake_data_done-time_start)
        #fo.write("time_fake_data_done:    " + str(time_fake_data_done) + "\n")
        
        self.local_model = LocalModel(model_config, fake_data)
        
        time_local_model_done = time.time()
        print("------------------------------------------------time_local_model_done: ", time_local_model_done-time_start)
        #fo.write("time_local_model_done:    " + str(time_local_model_done) + "\n")
        
        # ready to be dispatched for training
        self.sio.emit('client_ready', {
                'train_size': self.local_model.x_train.shape[0],
                'class_distr': my_class_distr  # for debugging, not needed in practice
            })
        
        time_after_emit = time.time()
        print("------------------------------------------------time_after_emit: ", time_after_emit-time_start)
        #fo.write("time_after_emit:    " + str(time_after_emit) + "\n")


    def register_handles(self):
        ########## Socket IO messaging ##########
        def on_connect():
            print('connect')

        def on_disconnect():
            print('disconnect')
            self.sio.disconnect(true)
            fo.close()
            f_training.close()

        def on_reconnect():
            print('reconnect')

        def on_request_update(*args):
            
            time_start_request_update = time.time()
            fo.write("time_start_request_update:    " + str(time_start_request_update) + "\n")
            print("------------------------------------------------time_start_request_update: ", time_start_request_update-time_start)
            
            req = args[0]
            # req:
            #     'model_id'
            #     'round_number'
            #     'current_weights'
            #     'weights_format'
            #     'run_validation'
            print("update requested")

            if req['weights_format'] == 'pickle':
                weights = pickle_string_to_obj(req['current_weights'])

            self.local_model.set_weights(weights)
            
            time_start_training = time.time()
            
            my_weights, train_loss, train_accuracy = self.local_model.train_one_round()
            
            time_end_training = time.time()
            f_training.write("time_training:    " + str(time_end_training-time_start_training) + "\n")
            
            resp = {
                'round_number': req['round_number'],
                'weights': obj_to_pickle_string(my_weights),
                'train_size': self.local_model.x_train.shape[0],
                'valid_size': self.local_model.x_valid.shape[0],
                'train_loss': train_loss,
                'train_accuracy': train_accuracy,
            }
            if req['run_validation']:
                valid_loss, valid_accuracy = self.local_model.validate()
                resp['valid_loss'] = valid_loss
                resp['valid_accuracy'] = valid_accuracy
            
            
            time_start_emit = time.time()
            fo.write("time_start_emit:    " + str(time_start_emit) + "\n")
            print("------------------------------------------------time_start_emit: ", time_start_emit-time_start)

            self.sio.emit('client_update', resp)
            
            time_finish_emit = time.time()
            #fo.write("time_finish_emit:    " + str(time_finish_emit) + "\n")
            print("------------------------------------------------time_finish_emit: ", time_finish_emit-time_start)


        def on_stop_and_eval(*args):
            req = args[0]
            if req['weights_format'] == 'pickle':
                weights = pickle_string_to_obj(req['current_weights'])
            self.local_model.set_weights(weights)
            test_loss, test_accuracy = self.local_model.evaluate()
            resp = {
                'test_size': self.local_model.x_test.shape[0],
                'test_loss': test_loss,
                'test_accuracy': test_accuracy
            }
            self.sio.emit('client_eval', resp)


        self.sio.on('connect', on_connect)
        self.sio.on('disconnect', on_disconnect)
        self.sio.on('reconnect', on_reconnect)
        self.sio.on('init', lambda *args: self.on_init(*args))
        self.sio.on('request_update', on_request_update)
        self.sio.on('stop_and_eval', on_stop_and_eval)




        # TODO: later: simulate datagen for long-running train-serve service
        # i.e. the local dataset can increase while training

        # self.lock = threading.Lock()
        # def simulate_data_gen(self):
        #     num_items = random.randint(10, FederatedClient.MAX_DATASET_SIZE_KEPT * 2)
        #     for _ in range(num_items):
        #         with self.lock:
        #             # (X, Y)
        #             self.collected_data_train += [self.datasource.sample_single_non_iid()]
        #             # throw away older data if size > MAX_DATASET_SIZE_KEPT
        #             self.collected_data_train = self.collected_data_train[-FederatedClient.MAX_DATASET_SIZE_KEPT:]
        #             print(self.collected_data_train[-1][1])
        #         self.intermittently_sleep(p=.2, low=1, high=3)

        # threading.Thread(target=simulate_data_gen, args=(self,)).start()

    
    def intermittently_sleep(self, p=.1, low=10, high=100):
        if (random.random() < p):
            time.sleep(random.randint(low, high))


# possible: use a low-latency pubsub system for gradient update, and do "gossip"
# e.g. Google cloud pubsub, Amazon SNS
# https://developers.google.com/nearby/connections/overview
# https://pypi.python.org/pypi/pyp2p

# class PeerToPeerClient(FederatedClient):
#     def __init__(self):
#         super(PushBasedClient, self).__init__()    


if __name__ == "__main__":
    
    fo = open("timeline_clinet.txt", "w")
    f_training = open("time_training.txt", "w")
    
    time_start = time.time()
    print("------------------------------------------------time_start: ", time_start)
    fo.write("time_start:    " + str(time_start) + "\n")
    
    FederatedClient("172.17.0.2", 1111, datasource.Mnist)
