__author__ = 'hiroki'

import sys
import time
from collections import defaultdict

from util import load_init_emb, PAD, UNK, RE_NUM, Vocab

import numpy as np
import theano
import theano.tensor as T
from theano.tensor.nnet.conv import conv2d

from nn_utils import build_shared_zeros, sample_weights, relu
from optimizers import sgd, ada_grad


class Model(object):
    def __init__(self, x, c, y, opt, lr, init_emb, vocab_size, char_size, window, n_emb, n_c_emb, n_h, n_c_h, n_y, reg=0.0001):
        """
        :param n_emb: dimension of word embeddings
        :param window: window size
        :param n_h: dimension of hidden layer
        :param n_y: number of tags
        x: 1D: batch size * window, 2D: emb_dim
        h: 1D: batch_size, 2D: hidden_dim
        """

        assert window % 2 == 1, 'Window size must be odd'

        """ input """
        self.x = x
        self.c = c
        self.y = y

        n_phi = n_emb + n_c_emb * window
        n_words = x.shape[0]

        """ params """
        if init_emb is not None:
            self.emb = theano.shared(init_emb)
        else:
            self.emb = theano.shared(sample_weights(vocab_size, n_emb))

        self.pad = build_shared_zeros((1, n_c_emb))
        self.e_c = theano.shared(sample_weights(char_size - 1, n_c_emb))
        self.emb_c = T.concatenate([self.pad, self.e_c], 0)

        self.W_in = theano.shared(sample_weights(n_h, 1, window, n_phi))
        self.W_c = theano.shared(sample_weights(n_c_h, 1, window, n_c_emb))
        self.W_h = theano.shared(sample_weights(n_h, n_h))
        self.W_out = theano.shared(sample_weights(n_h, n_y))
        self.params = [self.e_c, self.W_in, self.W_c, self.W_h, self.W_out]

        """ pad """
        self.zero = theano.shared(np.zeros(shape=(1, 1, window / 2, n_phi), dtype=theano.config.floatX))

        """ look up embedding """
        x_emb = self.emb[self.x]  # x_emb: 1D: n_words, 2D: n_emb
        c_emb = self.emb_c[self.c]  # c_emb: 1D: n_words, 2D: n_chars, 3D: n_c_emb

        """ create feature """
        c_phi = self.create_char_feature(c_emb)
        x_phi = T.concatenate([x_emb, c_phi], axis=1)

        """ convolution """
        x_padded = T.concatenate([self.zero, x_phi.reshape((1, 1, x_phi.shape[0], x_phi.shape[1])), self.zero], axis=2)  # x_padded: 1D: n_words + n_pad, 2D: n_phi
        x_in = conv2d(input=x_padded, filters=self.W_in)

        """ feed-forward computation """
        h = relu(T.dot(x_in.reshape((x_in.shape[1], x_in.shape[2])).T, self.W_h))
        self.p_y_given_x = T.nnet.softmax(T.dot(h, self.W_out)) + 0.00000001

        """ prediction """
        self.y_pred = T.argmax(self.p_y_given_x, axis=1)
        self.corrects = T.eq(self.y_pred, self.y)

        """ cost function """
        self.nll = -T.sum(T.log(self.p_y_given_x)[T.arange(n_words), self.y])

        self.cost = self.nll

        if opt == 'sgd':
            self.updates = sgd(self.cost, self.params, self.emb, x_emb, lr)
        else:
            self.updates = ada_grad(self.cost, self.params, self.emb, x_emb, self.x, lr)

    def create_char_feature(self, x_c):
        def forward(x_c_t, W):
#            c_conv = conv2d(input=x_c_t.reshape((1, 1, x_c_t.shape[0], x_c_t.shape[1])), filters=W)  # c_conv: 1D: n_c_h, 2D: n_char * slide
            c_conv = conv2d(input=x_c_t, filters=W)  # c_conv: 1D: n_c_h, 2D: n_char * slide
            c_t = T.max(c_conv.reshape((c_conv.shape[1], c_conv.shape[2])), axis=1)  # c_t.shape: (1, 50, b_t-b_tm1, 1)
            return c_t

        c, _ = theano.scan(fn=forward,
                           sequences=[x_c.reshape((x_c.shape[0], 1, 1, x_c.shape[1], x_c.shape[2]))],
                           outputs_info=[None],
                           non_sequences=[self.W_c])
        return c


def load_conll_char(path, _train, vocab_word, vocab_char=Vocab(), vocab_tag=Vocab(), vocab_size=None, file_encoding='utf-8'):
    corpus = []
    word_freqs = defaultdict(int)
    char_freqs = defaultdict(int)

    if vocab_word is None:
        register = True
        vocab_word = Vocab()
    else:
        register = False

    if register:
        vocab_word.add_word(UNK)

    if _train:
        vocab_char.add_word(PAD)
        vocab_char.add_word(UNK)

    with open(path) as f:
        wts = []
        for line in f:
            es = line.rstrip().split('\t')
            if len(es) == 10:
                word = es[1].decode(file_encoding)
                word = RE_NUM.sub(u'0', word)
                tag = es[4].decode(file_encoding)

                for c in word:
                    char_freqs[c] += 1

                wt = (word, tag)
                wts.append(wt)
                word_freqs[word.lower()] += 1
                vocab_tag.add_word(tag)
            else:
                # reached end of sentence
                corpus.append(wts)
                wts = []
        if wts:
            corpus.append(wts)

    if register:
        for w, f in sorted(word_freqs.items(), key=lambda (k, v): -v):
            if vocab_size is None or vocab_word.size() < vocab_size:
                vocab_word.add_word(w)
            else:
                break
    if _train:
        for c, f in sorted(char_freqs.items(), key=lambda (k, v): -v):
            vocab_char.add_word(c)

    return corpus, vocab_word, vocab_char, vocab_tag


def convert_into_ids(corpus, vocab_word, vocab_char, vocab_tag):
    id_corpus_w = []
    id_corpus_c = []
    id_corpus_t = []

    for sent in corpus:
        w_ids = []
        c_ids = []
        t_ids = []
        max_char_len = -1

        for w, t in sent:
            w_id = vocab_word.get_id(w.lower())
            t_id = vocab_tag.get_id(t)
            c_id_w = []

            if w_id is None:
                w_id = vocab_word.get_id(UNK)

            assert w_id is not None
            assert t_id is not None

            max_char_len = len(w) if max_char_len < len(w) else max_char_len

            for c in w:
                c_id = vocab_char.get_id(c)
                if c_id is None:
                    c_id = vocab_char.get_id(UNK)
                c_id_w.append(c_id)

            w_ids.append(w_id)
            t_ids.append(t_id)
            c_ids.append(c_id_w)

        id_corpus_w.append(np.asarray(w_ids, dtype='int32'))
        id_corpus_t.append(np.asarray(t_ids, dtype='int32'))
        id_corpus_c.append(np.asarray(zero_pad_char(c_ids, max_char_len), dtype='int32'))

    assert len(id_corpus_w) == len(id_corpus_c) == len(id_corpus_t)
    return id_corpus_w, id_corpus_c, id_corpus_t


def zero_pad_char(char_ids, max_char_len, window=5):
    new = []
    p = window / 2
    for c_ids in char_ids:  # char_ids: 1D: n_words, 2D: n_chars
        pre = [0 for i in xrange(p)]
        pad = [0 for i in xrange(max_char_len - len(c_ids) + p)]
        new.append(pre + c_ids + pad)
    return new


def train(args):
    print '\nNEURAL POS TAGGER START\n'

    print '\tINITIAL EMBEDDING\t%s' % args.init_emb
    print '\tWORD VECTOR\t\tEmb Dim: %d  Hidden Dim: %d' % (args.emb, args.hidden)
    print '\tCHARACTER VECTOR\tEmb Dim: %d  Hidden Dim: %d' % (args.c_emb, args.c_hidden)
    print '\tOPTIMIZATION\t\tMethod: %s  Learning Rate: %f  L2 Reg: %f' % (args.opt, args.lr, args.reg)

    """ load pre-trained embeddings """
    vocab_word = None
    init_emb = None
    if args.init_emb:
        print '\tLoading Embeddings...'
        init_emb, vocab_word = load_init_emb(args.init_emb)
        n_emb = init_emb.shape[1]
    else:
        n_emb = args.emb

    """ load data """
    print '\tLoading Data...'
    train_corpus, vocab_word, vocab_char, vocab_tag = load_conll_char(path=args.train_data, _train=True, vocab_word=vocab_word, vocab_size=args.vocab)
    dev_corpus, _, _, _ = load_conll_char(path=args.dev_data, _train=False, vocab_word=vocab_word, vocab_char=vocab_char)
    print '\tTrain Sentences: %d  Test Sentences: %d' % (len(train_corpus), len(dev_corpus))
    print '\tVocab size: %d  Char size: %d' % (vocab_word.size(), vocab_char.size())

    """ converting into ids """
    print '\tConverting into IDs...'
    # batches: 1D: n_batch, 2D: [0]=word id 2D matrix, [1]=tag id 2D matrix
    tr_sample_x, tr_sample_c, tr_sample_y = convert_into_ids(train_corpus, vocab_word, vocab_char, vocab_tag)
    dev_sample_x, dev_sample_c, dev_sample_y = convert_into_ids(dev_corpus, vocab_word, vocab_char, vocab_tag)

    """ symbol definition """
    n_c_emb = args.c_emb
    window = args.window
    opt = args.opt
    lr = args.lr
    reg = args.reg
    n_h = args.hidden
    n_c_h = args.c_hidden
    n_y = args.tag

    print '\tCompiling Theano Code...'
    x = T.ivector()
    c = T.imatrix()
    y = T.ivector()

    """ tagger set up """
    tagger = Model(x=x, c=c, y=y, opt=opt, lr=lr, init_emb=init_emb,
                   vocab_size=vocab_word.size(), char_size=vocab_char.size(), window=window,
                   n_emb=n_emb, n_c_emb=n_c_emb, n_h=n_h, n_c_h=n_c_h, n_y=n_y, reg=reg)

    train_model = theano.function(
        inputs=[x, c, y],
        outputs=[tagger.nll, tagger.corrects],
        updates=tagger.updates,
        mode='FAST_RUN'
    )

    valid_model = theano.function(
        inputs=[x, c, y],
        outputs=tagger.corrects,
        mode='FAST_RUN'
    )

    def _train():
        for epoch in xrange(args.epoch):
            print '\nEpoch: %d' % (epoch + 1)
            print '\tBatch Index: ',
            start = time.time()

            total = 0.0
            correct = 0
            losses = 0.0

            for index in xrange(len(tr_sample_x)):
                if index % 100 == 0 and index != 0:
                    print index,
                    sys.stdout.flush()

                loss, corrects = train_model(tr_sample_x[index], tr_sample_c[index], tr_sample_y[index])

                total += len(corrects)
                correct += np.sum(corrects)
                losses += np.mean(loss)

            end = time.time()
            print '\tTime: %f seconds' % (end - start)
            print '\tAverage Negative Log Likelihood: %f' % (losses / len(tr_sample_x))
            print '\tAccuracy:%f  Total:%d  Correct:%d' % ((correct / total), total, correct)

            _dev(valid_model)

    def _dev(model):
        print '\tBatch Index: ',
        start = time.time()

        total = 0.0
        correct = 0

        for index in xrange(len(dev_sample_x)):
            if index % 100 == 0 and index != 0:
                print index,
                sys.stdout.flush()

            corrects = model(dev_sample_x[index], dev_sample_c[index], dev_sample_y[index])

            total += len(corrects)
            correct += np.sum(corrects)

        end = time.time()
        print '\tTime: %f seconds' % (end - start)
        print '\tAccuracy:%f  Total:%d  Correct:%d' % ((correct / total), total, correct)

    _train()