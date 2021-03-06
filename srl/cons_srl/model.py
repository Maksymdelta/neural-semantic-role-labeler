import theano
import theano.tensor as T

from ..nn.nn import BaseUnit
from ..nn.rnn import GRU, LSTM
from ..nn.classifier import Softmax, CRF
from ..nn.nn_utils import L2_sqr, relu
from ..nn.optimizers import adam
from ..utils.io_utils import say


class Model(object):

    def __init__(self, argv, x, y, n_in, n_h, n_y, reg=0.0001):
        self.argv = argv
        self.unit = argv.unit
        self.depth = argv.layer
        self.connect = argv.connect

        self.x = x  # 1D: batch_size, 2D: n_words, 3D: n_fin
        self.y = y  # 1D: batch_size, 2D: n_words
        self.inputs = [x, y]
        self.layers = []
        self.params = []

        n_fin = n_in * 7 + 1

        ################
        # Set networks #
        ################
        self.set_layers(n_fin, n_h, n_y)
        self.set_params()

        #############
        # Computing #
        #############
        h1 = self.input_layer(x)
        h2 = self.mid_layer(h1)
        o = self.output_layer(h2)

        ##########
        # Scores #
        ##########
        self.p_y = self.get_y_scores(o, y.dimshuffle(1, 0))
        self.y_hat = self.decode(o)
        self.errors = T.neq(y, self.y_hat)

        ############
        # Training #
        ############
        self.nll = - T.mean(self.p_y)
        self.cost = self.nll + reg * L2_sqr(self.params) / 2.
        self.g = T.grad(self.cost, self.params)
        self.updates = adam(self.params, self.g)

    def set_layers(self, n_fin, n_h, n_y):
        unit = self._select_unit(self.unit)

        self.layers.append(BaseUnit(n_i=n_fin, n_h=n_h, activation=relu))
        for i in xrange(self.depth):
            self.layers.append(unit(n_i=n_h, n_h=n_h))
            if self.connect == 'agg':
                self.layers.append(BaseUnit(n_i=n_h*2, n_h=n_h, activation=relu))

        classifier = self._select_classifier(self.argv.classifier)
        self.layers.append(classifier(n_i=n_h, n_y=n_y))
        say('Hidden Layer: %d' % (len(self.layers) - 2))

    @staticmethod
    def _select_unit(unit_name):
        return GRU if unit_name.lower() == 'gru' else LSTM

    @staticmethod
    def _select_classifier(classifier_name):
        return CRF if classifier_name.lower() == 'crf' else Softmax

    def set_params(self):
        for l in self.layers:
            self.params += l.params
        say("num of parameters: {}\n".format(sum(len(x.get_value(borrow=True).ravel()) for x in self.params)))

    def input_layer(self, x):
        return self.layers[0].dot(x.dimshuffle(1, 0, 2))

    def mid_layer(self, x):
        if self.connect == 'agg':
            if self.unit == 'gru':
                return self._aggregation_connected_gru_layers(x)
            return self._aggregation_connected_lstm_layers(x)
        return self._residual_connected_layers(x)

    def _aggregation_connected_gru_layers(self, x):
        h0 = T.zeros_like(x[0], dtype=theano.config.floatX)
        for i in xrange(self.depth):
            h = self.layers[i*2+1].forward_all(x, h0)
            x = self.layers[i*2+2].dot(T.concatenate([x, h], axis=2))[::-1]
            h0 = x[0]

        if (self.depth % 2) == 1:
            x = x[::-1]

        return x

    def _aggregation_connected_lstm_layers(self, x):
        h0 = T.zeros_like(x[0], dtype=theano.config.floatX)
        c0 = T.zeros_like(x[0], dtype=theano.config.floatX)
        for i in xrange(self.depth):
            h, c = self.layers[i*2+1].forward_all(x, h0, c0)
            x = self.layers[i*2+2].dot(T.concatenate([x, h], axis=2))[::-1]
            h0 = x[0]
            c0 = c[-1]

        if (self.depth % 2) == 1:
            x = x[::-1]

        return x

    def _residual_connected_layers(self, x):
        h0 = T.zeros_like(x[0], dtype=theano.config.floatX)
        for i in xrange(self.depth):
            h = self.layers[i+1].forward_all(x, h0)
            x = (x + h)[::-1]
            h0 = h[-1]
        if (self.depth % 2) == 1:
            x = x[::-1]
        return x

    def output_layer(self, h):
        return self.layers[-1].forward(h)

    def decode(self, h):
        return self.layers[-1].decode(h)

    def get_y_scores(self, h, y):
        return self.layers[-1].get_y_prob(h, y)



