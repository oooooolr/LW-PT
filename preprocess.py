#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = "Han"
__email__ = "liuhan132@foxmail.com"

import os
import json
import codecs
import h5py
import pickle
import jieba
import numpy as np
from tqdm import tqdm
from gensim.models.word2vec import Word2Vec
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.model_selection import train_test_split
from utils.functions import set_seed

random_seed = 1


class BaseDataset:
    def __init__(self, data_path):
        self.data_path = data_path

    def build(self):
        return NotImplementedError

    def extract(self):
        return NotImplementedError

    def transform(self):
        return NotImplementedError

    def save(self, data, meta_data):
        return NotImplementedError


class RMSC(BaseDataset):
    """
    RMSC dataset
    - forked from "https://github.com/lancopku/RMSC"
    """

    def __init__(self, data_path):
        super(RMSC, self).__init__(data_path)
        self.emb_dim = 100
        self.max_sent = 40
        self.max_word = 20

        self.songs = os.listdir(self.data_path)
        self.sorted_total_tags = []
        self.all_comments_list = []
        self.total_song_comments_and_tags = []

        self.word2vec = None
        self.dict_tag = {}

    def build(self):
        """
        ETL pipeline
        :return:
        """
        print('building RMSC dataset...')
        self.extract()
        self.train_emb()
        data, meta_data = self.transform()
        self.save(data, meta_data)

    def extract(self):
        total_tags = []

        for song in tqdm(self.songs, desc='extracting...'):
            with codecs.open(self.data_path + '/' + song, 'r+', encoding='utf-8') as f:
                a = f.read()
                dict_f = json.loads(a)
                every_song_comment_for_lstm_train = []
                all_comments_dict = dict_f['all_short_comments'][:self.max_sent]
                for comment_dict in all_comments_dict:
                    every_comment = comment_dict["comment"]
                    every_comment_cut = "/".join(jieba.cut(every_comment, cut_all=False)).split('/')  # cur comment
                    every_song_comment_for_lstm_train.append(every_comment_cut)  # [[pl1],[pl2],...]
                every_song_comments_and_tags = {"tags": dict_f['tags'], "comments": every_song_comment_for_lstm_train}
                self.all_comments_list.extend(every_song_comment_for_lstm_train)  # get all comments
                total_tags.extend(dict_f['tags'])  # get all classes
                self.total_song_comments_and_tags.append(every_song_comments_and_tags)  # all tags and comments

        print('Songs:', len(self.songs))

        self.sorted_total_tags = sorted(list(set(total_tags)))  # all tags
        print('Tags:', len(self.sorted_total_tags))

    def train_emb(self):
        print('training word2vec...')
        self.word2vec = Word2Vec(self.all_comments_list, workers=4, min_count=1, seed=random_seed)
        self.word2vec.save("data/rmsc_word2vec.model")
        del self.all_comments_list
        print("word2vec info:", self.word2vec)

        for i, t in enumerate(self.sorted_total_tags):
            self.dict_tag[t] = i + 1

    def word_emb(self, word):
        return self.word2vec[word]

    def tag_emb(self, tag):
        return self.dict_tag[tag]

    def transform(self):
        labels_origin = []
        len_songs = len(self.total_song_comments_and_tags)
        embed_input = np.zeros((len_songs,
                                self.max_sent,
                                self.max_word,
                                self.emb_dim))

        # get input and label with embeddings
        len_every_comment_cutted = np.zeros((len_songs, self.max_sent))
        sum_comment_count = 0
        for i in tqdm(range(len_songs), desc='transforming...'):
            every_song_comment_words_embedding = np.zeros((self.max_sent, self.max_word, self.emb_dim))
            all_comments_in_every_song = self.total_song_comments_and_tags[i]["comments"]
            for j in range(len(all_comments_in_every_song)):
                every_comment_in_one_song = np.array(list(map(self.word_emb, all_comments_in_every_song[j])))
                every_comment_embedding = np.zeros((self.max_word, self.emb_dim))
                count_cur_comment = len(every_comment_in_one_song)
                sum_comment_count += count_cur_comment
                if count_cur_comment < self.max_word:
                    len_every_comment_cutted[i, j] = count_cur_comment
                    every_comment_embedding[0:count_cur_comment] = every_comment_in_one_song
                else:
                    every_comment_embedding = every_comment_in_one_song[0:self.max_word]
                    len_every_comment_cutted[i, j] = self.max_word
                    # print(count_cur_comment)
                every_song_comment_words_embedding[j] = every_comment_embedding
            embed_input[i] = every_song_comment_words_embedding
            every_song_comment_tags_embedding = np.array(
                list(map(self.tag_emb, self.total_song_comments_and_tags[i]["tags"])))
            labels_origin.append(every_song_comment_tags_embedding)
        del self.total_song_comments_and_tags
        print("average comment length", sum_comment_count / (len_songs * self.max_sent))
        labels = MultiLabelBinarizer().fit_transform(labels_origin)
        del labels_origin

        # de_rate = 0
        # soft_labels = (1 - de_rate) * labels + de_rate * (1 - labels)

        # split the data
        x_train, x_test_valid, y_train, y_test_valid, seq_train, seq_test_valid, songs_train, songs_test_valid = \
            train_test_split(embed_input, labels, len_every_comment_cutted, self.songs, test_size=0.3,
                             random_state=random_seed)
        # del soft_labels
        del embed_input
        del len_every_comment_cutted
        x_test, x_valid, y_test, y_valid, seq_test, seq_valid, songs_test, songs_valid = train_test_split(
            x_test_valid, y_test_valid, seq_test_valid, songs_test_valid, test_size=0.3, random_state=random_seed)
        # label_train, label_test_valid = train_test_split(labels, test_size=0.3, random_state=random_seed)
        # label_test, label_valid = train_test_split(label_test_valid, test_size=0.3, random_state=random_seed)
        print('train:', len(songs_train))
        print('valid:', len(songs_valid))
        print('test:', len(songs_test))

        data = {'x_train': x_train,
                'x_valid': x_valid,
                'x_test': x_test,
                'y_train': y_train,
                'y_valid': y_valid,
                'y_test': y_test,
                'seq_train': seq_train,
                'seq_valid': seq_valid,
                'seq_test': seq_test}
        meta_data = {'songs_train': songs_train,
                     'songs_valid': songs_valid,
                     'songs_test': songs_valid,
                     'sorted_tags': self.sorted_total_tags}

        return data, meta_data

    def save(self, data, meta_data):
        """
        Save to file
        :return:
        """
        print('saving data...')
        with open('data/rmsc.pickle', 'wb') as f:
            pickle.dump(data, f)

        print('saving meta-data...')
        with open('data/rmsc.pickle.meta', 'wb') as f:
            pickle.dump(meta_data, f)


if __name__ == '__main__':
    set_seed(random_seed)
    dataset = RMSC(data_path='data/rmsc/small')
    dataset.build()