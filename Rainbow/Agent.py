
import random
import numpy as np
import tensorflow as tf
from collections import deque

from Environment import Environment
from baselines.deepq.replay_buffer import PrioritizedReplayBuffer
from QNetwork import QNetwork
from Model import copy_vars


class Agent:

    def __init__(self, settings, sess, gui, displayer, saver):
        print("Initializing the agent...")

        self.settings = settings
        self.sess = sess
        self.gui = gui
        self.displayer = displayer
        self.saver = saver

        self.env = Environment(settings)

        self.mainQNetwork = QNetwork(settings, 'main')
        self.targetQNetwork = QNetwork(settings, 'target')

        self.buffer = PrioritizedReplayBuffer(settings.BUFFER_SIZE,
                                              settings.ALPHA)

        self.epsilon = settings.EPSILON_START
        self.beta = settings.BETA_START

        self.init_update_target = copy_vars(self.mainQNetwork.vars,
                                            self.targetQNetwork.vars,
                                            1, 'init_update_target')

        self.update_target = copy_vars(self.mainQNetwork.vars,
                                       self.targetQNetwork.vars,
                                       settings.UPDATE_TARGET_RATE,
                                       'update_target')

        self.nb_ep = 1
        self.best_run = -1e10
        self.n_gif = 0

    def pre_train(self):
        print("Beginning of the pre-training...")

        for i in range(self.settings.PRE_TRAIN_STEPS):

            s = self.env.reset()
            done = False
            episode_reward = 0
            episode_step = 0

            while episode_step < self.settings.MAX_EPISODE_STEPS and not done:

                a = self.env.act_random()
                s_, r, done, info = self.env.act(a)
                self.buffer.add(s, a, r, s_, done)

                s = s_
                episode_reward += r
                episode_step += 1

            if self.settings.PRE_TRAIN_STEPS > 5 and i % (self.settings.PRE_TRAIN_STEPS // 5) == 0:
                print("Pre-train step n", i)

            self.best_run = max(self.best_run, episode_reward)

        print("End of the pre training !")

    def run(self):
        print("Beginning of the run...")

        self.pre_train()
        self.sess.run(self.init_update_target)

        self.total_steps = 0
        self.nb_ep = 1

        while self.nb_ep < self.settings.TRAINING_STEPS and not self.gui.STOP:

            s = self.env.reset()
            episode_reward = 0
            done = False
            memory = deque()

            episode_step = 1
            max_step = self.settings.MAX_EPISODE_STEPS
            if self.settings.EP_ELONGATION > 0:
                max_step += self.nb_ep // self.settings.EP_ELONGATION

            # Render settings
            self.env.set_render(self.gui.render.get(self.nb_ep))
            self.env.set_gif(self.gui.gif.get(self.nb_ep))

            while episode_step <= max_step and not done:

                if random.random() < self.epsilon:
                    a = random.randint(0, self.settings.ACTION_SIZE - 1)
                else:
                    a, = self.sess.run(self.mainQNetwork.predict,
                                       feed_dict={self.mainQNetwork.inputs: [s]})

                s_, r, done, info = self.env.act(a)
                episode_reward += r

                memory.append((s, a, r, s_, 0 if done else 1))

                if len(memory) > self.settings.N_STEP_RETURN:
                    s_mem, a_mem, discount_R, ss_mem, done_mem = memory.popleft()
                    for i, (si, ai, ri, s_i, di) in enumerate(memory):
                        discount_R += ri * self.settings.DISCOUNT ** (i + 1)
                    self.buffer.add(s_mem, a_mem, discount_R, s_, done)

                if episode_step % self.settings.TRAINING_FREQ == 0:

                    train_batch = self.buffer.sample(self.settings.BATCH_SIZE,
                                                     self.beta)
                    # Incr beta
                    if self.beta <= self.settings.BETA_STOP:
                        self.beta += self.settings.BETA_INCR

                    feed_dict = {self.mainQNetwork.inputs: train_batch[3]}
                    mainQaction = self.sess.run(self.mainQNetwork.predict,
                                                feed_dict=feed_dict)

                    feed_dict = {self.targetQNetwork.inputs: train_batch[3]}
                    targetQvalues = self.sess.run(self.targetQNetwork.Qvalues,
                                                  feed_dict=feed_dict)

                    doubleQ = targetQvalues[range(self.settings.BATCH_SIZE),
                                            mainQaction]
                    targetQvalues = train_batch[2] + \
                        self.settings.DISCOUNT * doubleQ * train_batch[4]

                    feed_dict = {self.mainQNetwork.inputs: train_batch[0],
                                 self.mainQNetwork.Qtarget: targetQvalues,
                                 self.mainQNetwork.actions: train_batch[1]}
                    td_error, _ = self.sess.run([self.mainQNetwork.td_error,
                                                 self.mainQNetwork.train],
                                                feed_dict=feed_dict)

                    self.buffer.update_priorities(train_batch[6], td_error)

                    self.sess.run(self.update_target)

                s = s_
                episode_step += 1
                self.total_steps += 1

            self.nb_ep += 1

            # Decay epsilon
            if self.epsilon > self.settings.EPSILON_STOP:
                self.epsilon -= self.settings.EPSILON_DECAY

            self.displayer.add_reward(episode_reward, self.gui.plot.get(self.nb_ep))
            # if episode_reward > self.best_run and \
            #         self.nb_ep > 50 + self.settings.PRE_TRAIN_STEPS:
            #     self.best_run = episode_reward
            #     print("Save best", episode_reward)
            #     SAVER.save('best')
            #     self.play(1, 'results/gif/best.gif')

            if self.gui.ep_reward.get(self.nb_ep):
                print('Episode %2i, Reward: %7.3f, Steps: %i, Epsilon: %i'
                      ', Max steps: %i' % (self.nb_ep, episode_reward,
                                           episode_step, self.epsilon,
                                           max_step))

            # Save the model
            if self.gui.save.get(self.nb_ep):
                self.saver.save(self.nb_ep)

    def play(self, number_run, path=''):
        print("Playing for", number_run, "runs")

        try:
            for i in range(number_run):

                s = self.env.reset()
                episode_reward = 0
                done = False
                self.env.set_gif(True, path != '')

                while not done:
                    a, = self.sess.run(self.QNetwork.action,
                                       feed_dict={self.QNetwork.state_ph: [s]})
                    s, r, done, info = self.env.act(a)

                    episode_reward += r

                print("Episode reward :", episode_reward)

        except KeyboardInterrupt as e:
            pass

        except Exception as e:
            print("Exception :", e)

        finally:
            print("End of the demo")
            self.env.close()

    def stop(self):
        self.env.close()
