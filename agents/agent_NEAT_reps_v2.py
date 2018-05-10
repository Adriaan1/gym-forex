# Simplified version of the modified version of the Lander example included with neat-python for forex_env
from __future__ import print_function
# Imports
import gym
import gym.wrappers
from gym.envs.registration import register
import gym_forex
import json
import matplotlib.pyplot as plt
import multiprocessing
import neat
import numpy as np
import os
import pickle
import random
import time
import requests
import visualize
import sys
from copy import deepcopy
from neat.six_util import iteritems, itervalues
# Multi-core machine support
NUM_CORES = 1
# Make with the Name of the environment defined in gym_forex/__init__.py

env = gym.make('Forex-v0')
# Shows the action and observation space from the forex_env, its observation space is
# bidimentional, so it has to be converted to an array with nn_format() for direct ANN feed. (Not if evaluating with external DQN)
print("action space: {0!r}".format(env.action_space))
print("observation space: {0!r}".format(env.observation_space))
env = gym.wrappers.Monitor(env, 'results', force=True)
# First argument is the dataset, second is the  url
my_url=sys.argv[2]

# LanderGenome class
class LanderGenome(neat.DefaultGenome):
    def __init__(self, key):
        super().__init__(key)
        self.discount = None

    def configure_new(self, config):
        super().configure_new(config)
        self.discount = 0.01 + 0.98 * random.random()

    def configure_crossover(self, genome1, genome2, config):
        super().configure_crossover(genome1, genome2, config)
        self.discount = random.choice((genome1.discount, genome2.discount))

    def mutate(self, config):
        super().mutate(config)
        self.discount += random.gauss(0.0, 0.05)
        self.discount = max(0.01, min(0.99, self.discount))

    def distance(self, other, config):
        dist = super().distance(other, config)
        disc_diff = abs(self.discount - other.discount)
        return dist + disc_diff

    def __str__(self):
        return "Reward discount: {0}\n{1}".format(self.discount,
                                                  super().__str__())

# converts a bidimentional matrix to an one-dimention array
def nn_format(obs):
    output=[]
    for arr in obs:
        for val in arr:
            output.append(val)
    return output

class PooledErrorCompute(object):
    def __init__(self):
        self.pool = None if NUM_CORES < 2 else multiprocessing.Pool(NUM_CORES)
        self.test_episodes = []
        self.generation = 0

        self.min_reward = -15
        self.max_reward = 15

        self.episode_score = []
        self.episode_length = []

    def simulate(self, nets):
        scores = []
        self.test_episodes = []
        for genome, net in nets:
            observation = env.reset()
            step = 0
            data = []
            while 1:
                step += 1
                output = net.activate(nn_format(observation))
                #print("output: {0!r}".format(output))
                action = np.argmax(output)
                #print("observation: {0!r}".format(self.nn_format(observation)))
                #print("action: {0!r}".format(action))
                observation, reward, done, info = env.step(action)
                data.append(np.hstack((nn_format(observation), action, reward)))
                if done:
                    break

            data = np.array(data)
            score = np.sum(data[:,-1])
            self.episode_score.append(score)
            scores.append(score)
            self.episode_length.append(step)

            self.test_episodes.append((score, data))

        print("Score range [{:.3f}, {:.3f}]".format(min(scores), max(scores)))
        return scores

    def evaluate_genomes(self, genomes, config):
        self.generation += 1

        t0 = time.time()
        nets = []
        for gid, g in genomes:
            nets.append((g, neat.nn.FeedForwardNetwork.create(g, config)))

        print("network creation time {0}".format(time.time() - t0))
        t0 = time.time()

        # Periodically generate a new set of episodes for comparison.
        #if 1 == self.generation % 10:
        #self.test_episodes = self.test_episodes[-300:]
        scores=self.simulate(nets)
        print("simulation run time {0}".format(time.time() - t0))
        t0 = time.time()

        # Assign a composite fitness to each genome; genomes can make progress either
        # by improving their total reward or by making more accurate reward estimates.

        print("Evaluating {0} test episodes".format(len(self.test_episodes)))

        i = 0
        for genome, net in nets:
            #reward_error = compute_fitness(genome, net, self.test_episodes, self.min_reward, self.max_reward)
            genome.fitness = scores[i]
            i = i + 1
        print("final fitness compute time {0}\n".format(time.time() - t0))


def run():
    # Load the config file, which is assumed to live in
    # the same directory as this script.
    local_dir = os.path.dirname(__file__)
    config_path = os.path.join(local_dir, 'config')
    config = neat.Config(LanderGenome, neat.DefaultReproduction,
                         neat.DefaultSpeciesSet, neat.DefaultStagnation,
                         config_path)

    pop = neat.Population(config)
    stats = neat.StatisticsReporter()
    pop.add_reporter(stats)
    pop2 = neat.Population(config)
    stats2 = neat.StatisticsReporter()
    pop.add_reporter(stats)
    pop2.add_reporter(stats2)
    pop.add_reporter(neat.StdOutReporter(True))
    # Checkpoint every 25 generations or 900 seconds.
    rep = neat.Checkpointer(25, 900)
    pop.add_reporter(rep)

    # asigna un gen_best para poder cargar los demás desde syn
    for g in itervalues(pop.population):
        gen_best=g
        g.fitness = -10000000.0


    # Run until the winner from a generation is able to solve the environment
    # or the user interrupts the process.
    ec = PooledErrorCompute()
    temp = 0
    while 1:
        try:
            if temp >= 0:
                # TODO: FUNCION DE SINCRONIZACION CON SINGULARITY
                # Lee en pop2 el último checkpoint desde syn
                # Hace request de getLastParam(process_hash,use_current) a syn TODO: HACER PROCESS CONFIGURABLE Y POR HASH no por id
                res = requests.get(
                    my_url+"/processes/1?username=harveybc&pass_hash=$2a$04$ntNHmofQoMoajG89mTEM2uSR66jKXBgRQJnCgqfNN38aq9UkN4Y6q&process_hash=ph")
                cont = res.json()
                print('\ncurrent_block_performance =', cont['result'][0]['current_block_performance'])
                print('\nlast_optimum_id =', cont['result'][0]['last_optimum_id'])
                last_optimum_id = cont['result'][0]['last_optimum_id']
                # Si el perf reportado pop2_champion_fitness > pop1_champion_fitness
                best_fitness = gen_best.fitness
                print('\nbest_fitness =', best_fitness)
                if cont['result'][0]['current_block_performance'] > best_fitness:
                    # hace request GetParameter(id)
                    res_p = requests.get(
                        my_url+"/parameters/" + str(
                            last_optimum_id) + "?username=harveybc&pass_hash=$2a$04$ntNHmofQoMoajG89mTEM2uSR66jKXBgRQJnCgqfNN38aq9UkN4Y6q&process_hash=ph")
                    cont_param = res_p.json()
                    # descarga el checkpoint del link de la respuesta si cont.parameter_link
                    print('\ncont_param =', cont_param)
                    print('\nmigrations =')
                    if cont_param['result'][0]['parameter_link'] is not None:
                        genom_data = requests.get(cont_param['result'][0]['parameter_link']).content
                        with open('remote_reps', 'wb') as handler:
                            handler.write(genom_data)
                            handler.close()
                        # carga genom descargado en nueva población pop2
                        with open('remote_reps', 'rb') as f:
                            remote_reps = pickle.load(f)
                        # OP.MIGRATION: Reemplaza el peor de la especie pop1 más cercana por el nuevo chmpion de pop2 como http://neo.lcc.uma.es/Articles/WRH98.pdf
                        # para cada elemento de remote_reps, busca el closer, si remote fitness > local, lo reemplaza
                        for i in range(len(remote_reps)):
                            closer = None
                            min_dist = None
                            for g in itervalues(pop.population):
                                if g not in remote_reps:
                                    dist = g.distance(remote_reps[i], config.genome_config)
                                else:
                                    dist=100000000
                                # do not count already migrated remote_reps
                                if closer is None or min_dist is None:
                                    closer = deepcopy(g)
                                    min_dist = dist
                                if dist < min_dist:
                                    closer = deepcopy(g)
                                    min_dist = dist
                            # For the best genom in position 0
                            if i==0:
                                tmp_genom = deepcopy(remote_reps[i])
                               # Hack: overwrites original genome key with the replacing one
                                tmp_genom.key = closer.key
                                pop.population[closer.key] = deepcopy(tmp_genom)
                                print(" gen_best=", closer.key)
                                pop.best_genome=deepcopy(tmp_genom)
                                gen_best = deepcopy(tmp_genom)
                            else:
                                # si el remote fitness>local, reemplazar el remote de pop2 en pop1
                                if closer is not None:
                                    if closer not in remote_reps:
                                        # ADicionada condición para que NO migre el campeón, solo los reps (prueba)
                                        if closer.fitness is not None and remote_reps[i].fitness is not None:
                                            if remote_reps[i].fitness>closer.fitness:
                                                tmp_genom = deepcopy(remote_reps[i])
                                                # Hack: overwrites original genome key with the replacing one
                                                tmp_genom.key = closer.key
                                                pop.population[closer.key] = deepcopy(tmp_genom)
                                                print("Replaced=",closer.key)
                                                # actualiza gen_best y best_genome al remoto
                                                pop.best_genome = deepcopy(tmp_genom)
                                                gen_best = deepcopy(tmp_genom)
                                        if closer.fitness is None:
                                            tmp_genom = deepcopy(remote_reps[i])
                                            # Hack: overwrites original genome key with the replacing one
                                            tmp_genom.key = len(pop.population) + 1
                                            pop.population.add(tmp_genom)
                                            print("Created Por fitness=NONE : ", tmp_genom.key)
                                            # actualiza gen_best y best_genome al remoto
                                            pop.best_genome = deepcopy(tmp_genom)
                                            gen_best = deepcopy(tmp_genom)
                                    else:
                                        #si closer está en remote_reps es porque no hay ningun otro cercano así que lo adiciona
                                        tmp_genom = deepcopy(remote_reps[i])
                                        # Hack: overwrites original genome key with the replacing one
                                        tmp_genom.key = len(pop.population)+1
                                        pop.population.append(tmp_genom)
                                        print("Created=", tmp_genom.key)
                                        # actualiza gen_best y best_genome al remoto
                                        pop.best_genome = deepcopy(tmp_genom)
                                        gen_best = deepcopy(tmp_genom)


                        #ejecuta speciate
                        pop.species.speciate(config, pop.population, pop.generation)
                        print("\nSpeciation after migration done")
                # Si el perf reportado es menor pero no igual al de pop1
                if cont['result'][0]['current_block_performance'] < best_fitness:
                    # Obtiene remote_reps
                    # hace request GetParameter(id)
                    remote_reps=None
                    res_p = requests.get(
                        my_url + "/parameters/" + str(
                            last_optimum_id) + "?username=harveybc&pass_hash=$2a$04$ntNHmofQoMoajG89mTEM2uSR66jKXBgRQJnCgqfNN38aq9UkN4Y6q&process_hash=ph")
                    cont_param = res_p.json()
                    # descarga el checkpoint del link de la respuesta si cont.parameter_link
                    print('\ncont_param =', cont_param)
                    print('\nmigrations =')
                    if cont_param['result'][0]['parameter_link'] is not None:
                        genom_data = requests.get(cont_param['result'][0]['parameter_link']).content
                        with open('remote_reps', 'wb') as handler:
                            handler.write(genom_data)
                            handler.close()
                        # carga genom descargado en nueva población pop2
                        with open('remote_reps', 'rb') as f:
                            remote_reps = pickle.load(f)
                   #Guarda los mejores reps
                    reps_local=[]
                    reps=[gen_best]
                    # Para cada especie, adiciona su representative a reps
                    for sid, s in iteritems(pop.species.species):
                        #print("\ns=",s)
                        if s.representative not in reps_local:
                            reps_local.append(pop.population[s.representative.key])
                    # TODO: Conservar los mejores reps, solo reemplazarlos por los mas cercanos
                    if remote_reps is None:
                        for l in reps_local:
                            reps.append(l)
                    else:
                        # para cada reps_local l
                        for l in reps_local:
                            # busca el closer a l en reps_remote
                            for i in range(len(remote_reps)):
                                closer = None
                                min_dist = None
                                for g in reps_local:
                                    if g not in remote_reps:
                                        dist = g.distance(remote_reps[i], config.genome_config)
                                    else:
                                        dist=100000000
                                    # do not count already migrated remote_reps
                                    if closer is None or min_dist is None:
                                        closer = deepcopy(g)
                                        min_dist = dist
                                    if dist < min_dist:
                                        closer = deepcopy(g)
                                        min_dist = dist
                 #           si closer is in reps
                            if closer in reps:
                 #               adiciona l a reps si ya no estaba en reps
                                if l not in reps:
                                    reps.append(l)
                 #           sino
                            else:
                 #               si l tiene más fitness que closer,
                                if closer.fitness is not None or l.fitness is not None:
                                    if l.fitness>pop.population[closer.key].fitness:
                 #                       adiciona l a reps si ya no estaba en reps
                                        if l not in reps:
                                            reps.append(l)
                 #               sino
                                    else:
                 #                      adiciona closer a reps si ya no estaba en reps
                                        if l not in reps:
                                            reps.append(pop.population[closer.key])
                                            # Guarda checkpoint de los representatives de cada especie y lo copia a ubicación para servir vía syn.
                                            # rep.save_checkpoint(config,pop,neat.DefaultSpeciesSet,rep.current_generation)
                    print("\nreps=",reps)
                    filename = '{0}{1}'.format("reps-", rep.current_generation)
                    with open(filename, 'wb') as f:
                        pickle.dump(reps, f)
                    # Hace request de CreateParam a syn
                    form_data = {"process_hash": "ph", "app_hash": "ah",
                                 "parameter_link": my_url+"/genoms/" + filename,
                                 "parameter_text": pop.best_genome.key, "parameter_blob": "", "validation_hash": "",
                                 "hash": "h", "performance": best_fitness, "redir": "1", "username": "harveybc",
                                 "pass_hash": "$2a$04$ntNHmofQoMoajG89mTEM2uSR66jKXBgRQJnCgqfNN38aq9UkN4Y6q"}
                    # TODO: COLOCAR DIRECCION CONFIGURABLE
                    res = requests.post(
                        my_url+"/parameters?username=harveybc&pass_hash=$2a$04$ntNHmofQoMoajG89mTEM2uSR66jKXBgRQJnCgqfNN38aq9UkN4Y6q&process_hash=ph",
                        data=form_data)
                    res_json = res.json()
                # TODO FIN: FUNCION DE SINCRONIZACION CON SINGULARITY
            temp = temp + 1

            gen_best = pop.run(ec.evaluate_genomes, 5)

            #print(gen_best)
            visualize.plot_stats(stats, ylog=False, view=False, filename="fitness.svg")
            plt.plot(ec.episode_score, 'g-', label='score')
            plt.plot(ec.episode_length, 'b-', label='length')
            plt.grid()
            plt.legend(loc='best')
            plt.savefig("scores.svg")
            plt.close()

            mfs = sum(stats.get_fitness_mean()[-3:]) / 3.0
            print("Average mean fitness over last 3 generations: {0}".format(mfs))

            mfs = sum(stats.get_fitness_stat(min)[-3:]) / 3.0
            print("Average min fitness over last 3 generations: {0}".format(mfs))

            # Use the best genome to evaluate an environment.
            best_genomes = stats.best_unique_genomes(3)
            solved = True
            best_scores = []
            observation = env.reset()
            score = 0.0
            step = 0
            gen_best_nn=neat.nn.FeedForwardNetwork.create(gen_best, config)
            while 1:
                step += 1
                output = gen_best_nn.activate(nn_format(observation))
                best_action = np.argmax(output)
                observation, reward, done, info = env.step(best_action)
                score += reward
                env.render()
                if done:
                    break
            ec.episode_score.append(score)
            ec.episode_length.append(step)
            best_scores.append(score)
            avg_score = sum(best_scores) / len(best_scores)
            print("\nScore score=", score, " avg_score=",avg_score)

            if avg_score < 2000000000:
                solved = False

            if solved:
                print("Solved.")

                # Save the winners.
                for n, g in enumerate(best_genomes):
                    name = 'winner-{0}'.format(n)
                    with open(name+'.pickle', 'wb') as f:
                        pickle.dump(g, f)

                    visualize.draw_net(config, g, view=False, filename=name+"-net.gv")
                    visualize.draw_net(config, g, view=False, filename=name+"-net-enabled.gv",
                                       show_disabled=False)
                    visualize.draw_net(config, g, view=False, filename=name+"-net-enabled-pruned.gv",
                                       show_disabled=False, prune_unused=True)

                break
        except KeyboardInterrupt:
            print("User break.")
            break

    env.close()


if __name__ == '__main__':
    run()