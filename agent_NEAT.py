# -*- coding: utf-8 -*-
import random
import gym
import numpy as np
from collections import deque
from keras.optimizers import Adam
from keras import backend as K
from keras.models import Sequential
from keras.layers import Conv2D,Conv1D, MaxPooling2D, MaxPooling1D
from keras.layers import Activation, Dropout, Flatten, Dense
from keras.optimizers import SGD


EPISODES = 2000
import pickle


import neat


class DQNAgent:
    def __init__(self, state_size, action_size):
        self.state_size = state_size
        self.action_size = action_size
        self.memory = deque(maxlen=32000) #originalmente 2k
        self.gamma = 0.95    # discount rate
        self.epsilon = 1.0  # exploration rate
        self.epsilon_min = 0.001 # originalmente 0.01
        self.epsilon_decay = 0.992 # originalmente 0.99
        self.learning_rate = 0.01 #originalmente 0.001
        self.model = self._build_model()
        self.target_model = self._build_model()
        self.update_target_model()

    def _huber_loss(self, target, prediction):
        # sqrt(1+error^2)-1
        error = prediction - target
        return K.mean(K.sqrt(1+K.square(error))-1, axis=-1)

    def _build_model(self):
        # Deep Conv Neural Net for Deep-Q learning Model
        # LeNet model for 1D
        model = Sequential()
        # for observation[19][48], 19 vectors of 128-dimensional vectors,input_shape = (19, 48)
        # first set of CONV => RELU => POOL
        model.add(Conv1D(20, 5, input_shape=(19,48)))
        model.add(Activation('relu'))
        model.add(MaxPooling1D(pool_size=2, strides=2))
        # second set of CONV => RELU => POOL
        model.add(Conv1D(50, 5))
        model.add(Activation('relu'))
        model.add(MaxPooling1D(pool_size=2, strides=2))
        # set of FC => RELU layers
        model.add(Flatten())  # this converts our 3D feature maps to 1D feature vectors
        model.add(Dense(500))
        model.add(Activation('relu'))

        # Softmax activation since we neet to chose only one of athe available actions
        model.add(Dense(self.action_size))
        model.add(Activation('softmax'))
        # use SGD optimizer
        opt = SGD(lr=self.learning_rate)
        model.compile(loss="categorical_crossentropy", optimizer=opt,
                      metrics=["accuracy"])
        #model.compile(loss='binary_crossentropy',
        #              optimizer='rmsprop',
        #              metrics=['accuracy'])

        return model

    def update_target_model(self):
        # copy weights from model to target_model
        self.target_model.set_weights(self.model.get_weights())

    def remember(self, state, action, reward, next_state, done):
        self.memory.append((state, action, reward, next_state, done))

    def act(self, state):
        if np.random.rand() <= self.epsilon:
            return random.randrange(self.action_size)
        act_values = self.model.predict(state)
        return np.argmax(act_values[0])  # returns action

    def replay(self, batch_size):
        minibatch = random.sample(self.memory, batch_size)
        for state, action, reward, next_state, done in minibatch:
            #state = np.expand_dims(state, axis=0)
            #next_state = np.expand_dims(next_state, axis=0)
            target = self.model.predict(state)
            if done:
                target[0][action] = reward
            else:
                a = self.model.predict(next_state)[0]
                t = self.target_model.predict(next_state)[0]
                target[0][action] = reward + self.gamma * t[np.argmax(a)]
            self.model.fit(state, target, epochs=1, verbose=0)
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

    def load(self, name):
        self.model.load_weights(name)

    def save(self, name):
        self.model.save_weights(name)


if __name__ == "__main__":
    env = gym.make('Forex-v0')
    state_size = env.observation_space.shape[0]
    action_size = env.action_space.n
    agent = DQNAgent(state_size, action_size)
    # agent.load("./save/cartpole-ddqn.h5")
    done = False
    batch_size = 48
    # muestra si hay soporte de GPU
    #from tensorflow.python.client import device_lib
    #print(device_lib.list_local_devices())

    for e in range(EPISODES):
        state = env.reset()
        state = np.reshape(state, [19,state_size])
        state = np.expand_dims(state, axis=0)
        time=0
        points=0.0
        done = False
        while not done:
            # env.render()
            #load data in the observation buffer(action=0 for the first 1440 observations)
            if time>state_size:
                action = agent.act(state)
            else:
                action=0
                #TODO  :  REWARD COMO FUNCION DE NUM ORDENES AL DIA (4? Gauss?)
            next_state, reward, done, _ = env.step(action)
            reward = reward if not done else 0
            next_state = np.reshape(next_state, [19,state_size])
            next_state = np.expand_dims(next_state, axis=0)
            if time>state_size:
                agent.remember(state, action, reward, next_state, done)
            state = next_state
            time=time+1
            points += reward
            #print("e:{}/{},t:{},p:{},e:{:.2}-".format(e, EPISODES, time, points,agent.epsilon))
            if done:
                agent.update_target_model()
                print("episode Done: {}/{} ,reward: {} e: {:.2},".format(e, EPISODES, points,agent.epsilon))
                break
        if len(agent.memory) > batch_size:
            agent.replay(batch_size)
        # if e % 10 == 0:
        #     agent.save("./save/cartpole-ddqn.h5")
