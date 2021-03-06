"""Evaluate RL algorithms on the Jitterbug task suite"""

import os
import sys
import gym
import time
import pprint
import random
import warnings
import datetime
import multiprocessing

import numpy as np

# Suppress tensorflow deprecation warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="tensorflow")
warnings.filterwarnings("ignore", category=FutureWarning, module="tensorboard")

# Important: the below 3 imports must be in this order, or the program
# crashes under Ubuntu due to a protocol buffer version mismatch error
import tensorflow as tf
import stable_baselines
from dm_control import suite

# Import agents from stable_baselines
from stable_baselines import DDPG, PPO2, SAC, TD3
from stable_baselines.ddpg.noise import OrnsteinUhlenbeckActionNoise, NormalActionNoise

# Get some extra utilities
from stable_baselines.bench import Monitor
from stable_baselines.common.vec_env import DummyVecEnv, SubprocVecEnv

# from stable_baselines.results_plotter import load_results, ts2xy

# Add root folder to path so we can access benchmarks module
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    ".."
))
import jitterbug_dmc
from jitterbug_dmc import augmented_jitterbug


class CustomPolicyDDPG(stable_baselines.ddpg.policies.FeedForwardPolicy):
    """A DDPG specific FeedForward policy"""

    def __init__(self, *args, **kwargs):
        super(CustomPolicyDDPG, self).__init__(
            *args,
            **kwargs,
            layers=[350, 250],
            feature_extraction="mlp",
            act_fun=tf.nn.relu
        )


class CustomPolicyGeneral(stable_baselines.common.policies.FeedForwardPolicy):
    """A general Actor-Critic  policy"""

    def __init__(self, *args, **kwargs):
        super(CustomPolicyGeneral, self).__init__(
            *args,
            **kwargs,
            net_arch=[350, 250],
            feature_extraction="mlp",
            act_fun=tf.nn.relu
        )


def train(
        task,
        alg,
        logdir,
        domain_name,
        *,
        random_seed=None,
        num_steps=int(2e3),
        log_every=int(10e3),
        num_parallel=8,
        load_policy=False,
        load_policy_dir="",
        **kwargs
):
    """Train and evaluate an agent

    Args:
        task (str): Jitterbug task to train on
        alg (str): Algorithm to train, one of;
            - 'ddpg': DDPG Algorithm
            - 'ppo2': PPO2 Algorithm
            - 'sac': SAC Algorithm
        logdir (str): Logging directory
        domain_name (str): Name of the DMC domain

        random_seed (int): Random seed to use, or None
        num_steps (int): Number of training steps to train for
        log_every (int): Save and log progress every this many timesteps
        num_parallel (int): Number of parallel environments to run. Only used
        load_policy (bool): Whether to load an existing or not. It Yes, the policy is loaded from logdir.
            for A2C and PPO2.
    """

    assert alg in ('ddpg', 'sac', 'ppo2', 'td3'), "Invalid alg: {}".format(alg)
    assert domain_name in ('jitterbug', 'augmented_jitterbug'), "Invalid domain_name: {}".format(domain_name)

    # Cast args to types
    if random_seed is not None:
        random_seed = int(random_seed)
    else:
        random_seed = int(time.time())

    # Fix random seed
    random.seed(random_seed)
    np.random.seed(random_seed)

    # Prepare the logging directory
    os.makedirs(logdir, exist_ok=True)

    print("Training {} on {} with seed {} for {} steps "
          "(log every {}), saving to {}".format(
        alg,
        task,
        random_seed,
        num_steps,
        log_every,
        logdir
    ))

    if domain_name == "augmented_jitterbug":
        augmented_jitterbug.augment_Jitterbug(modify_legs=True,
                                              modify_mass=True,
                                              modify_coreBody1=False,
                                              modify_coreBody2=False,
                                              modify_global_density=False,
                                              modify_gear=False,
                                              )
    # Construct DMC env
    env_dmc = suite.load(
        domain_name=domain_name,
        task_name=task,
        task_kwargs=dict(random=random_seed, norm_obs=True),
        environment_kwargs=dict(flat_observation=True)
    )

    # Wrap gym env in a dummy parallel vector
    if alg in ('ppo2'):

        if num_parallel > multiprocessing.cpu_count():
            warnings.warn("Number of parallel workers "
                          "({}) > CPU count ({}), setting to # CPUs - 1".format(
                num_parallel,
                multiprocessing.cpu_count()
            ))
            num_parallel = max(
                1,
                multiprocessing.cpu_count() - 1
            )

        print("Using {} parallel environments".format(num_parallel))
        # XXX ajs 13/Sep/19 Hack to create multiple monitors that don't write to the same file
        env_vec = SubprocVecEnv([
            lambda: Monitor(
                gym.wrappers.FlattenDictWrapper(
                    jitterbug_dmc.JitterbugGymEnv(env_dmc),
                    dict_keys=["observations"]
                ),
                os.path.join(logdir, str(random.randint(0, 99999999))),
                allow_early_resets=True
            )
            for n in range(num_parallel)
        ])

    else:

        num_parallel = 1
        env_vec = DummyVecEnv([
            lambda: Monitor(
                gym.wrappers.FlattenDictWrapper(
                    jitterbug_dmc.JitterbugGymEnv(env_dmc),
                    dict_keys=["observations"]
                ),
                logdir,
                allow_early_resets=True
            )
        ])

    # Record start time
    start_time = datetime.datetime.now()

    def _cb(_locals, _globals):
        """Callback for during training"""

        if 'last_num_eps' not in _cb.__dict__:
            _cb.last_num_eps = 0

        # Extract episode reward history based on model type
        if isinstance(_locals['self'], DDPG):
            ep_r_hist = list(_locals['episode_rewards_history'])
        elif isinstance(_locals['self'], PPO2):
            ep_r_hist = [d['r'] for d in _locals['ep_info_buf']]
        elif isinstance(_locals['self'], SAC):
            ep_r_hist = [d['r'] for d in _locals['ep_info_buf']]
        elif isinstance(_locals['self'], TD3):
            ep_r_hist = [d['r'] for d in _locals['ep_info_buf']]
        else:
            raise ValueError("Invalid algorithm: {}".format(
                _locals['self']
            ))

        # Compute # elapsed steps based on # elapsed episodes
        ep_size = int(
            jitterbug_dmc.jitterbug.DEFAULT_TIME_LIMIT /
            jitterbug_dmc.jitterbug.DEFAULT_CONTROL_TIMESTEP
        )
        num_eps = len(ep_r_hist)
        elapsed_steps = ep_size * num_eps

        # Compute elapsed time in seconds
        elapsed_time = (datetime.datetime.now() - start_time).total_seconds()

        # Log some info
        if num_eps != _cb.last_num_eps:
            _cb.last_num_eps = num_eps

            print("{:.2f}s | {}ep | {}#: episode reward = "
                  "{:.2f}, last 5 episode reward = {:.2f}".format(
                elapsed_time,
                num_eps,
                elapsed_steps,
                ep_r_hist[-1],
                np.mean(ep_r_hist[-5:])
            ))

            # Save model checkpoint
            model_path = os.path.join(logdir, "model.pkl")
            print("Saved checkpoint to {}".format(model_path))
            _locals['self'].save(model_path)

        return True

    if alg == 'ddpg':

        # Default parameters for DDPG
        # kwargs.setdefault("normalize_returns", True)
        # kwargs.setdefault("return_range", (0., 1.))
        # kwargs.setdefault("normalize_observations", True)
        # kwargs.setdefault("observation_range", (-1., 1.))

        kwargs.setdefault("batch_size", 256)

        kwargs.setdefault("actor_lr", 1e-4)
        kwargs.setdefault("critic_lr", 1e-4)

        kwargs.setdefault("buffer_size", 1000000)

        kwargs.setdefault("action_noise", OrnsteinUhlenbeckActionNoise(
            mean=np.array([0.3]),
            sigma=0.3,
            theta=0.15
        ))

        print("Constructing DDPG agent with settings:")
        pprint.pprint(kwargs)

        # Construct the agent
        if load_policy:
            print("Load DDPG agent from ", load_policy_dir)
            agent = DDPG.load(load_path=os.path.join(load_policy_dir, "model.final.pkl"),
                              policy=CustomPolicyDDPG,
                              env=env_vec,
                              verbose=1,
                              tensorboard_log=logdir,
                              **kwargs
                              )
        else:
            agent = DDPG(
                policy=CustomPolicyDDPG,
                env=env_vec,
                verbose=1,
                tensorboard_log=logdir,
                **kwargs
            )

        # Train for a while (logging and saving checkpoints as we go)
        agent.learn(
            total_timesteps=num_steps,
            callback=_cb
        )

    elif alg == 'ppo2':

        kwargs.setdefault("learning_rate", 1e-4)
        kwargs.setdefault("n_steps", 256 // num_parallel)
        kwargs.setdefault("ent_coef", 0.01)
        kwargs.setdefault("cliprange", 0.1)

        print("Constructing PPO2 agent with settings:")
        pprint.pprint(kwargs)

        if load_policy:
            print("Load PPO2 agent from ", load_policy_dir)
            agent = PPO2.load(load_path=os.path.join(load_policy_dir, "model.final.pkl"),
                              policy=CustomPolicyGeneral,
                              env=env_vec,
                              verbose=1,
                              tensorboard_log=logdir,
                              **kwargs
                              )
        else:
            agent = PPO2(
                policy=CustomPolicyGeneral,
                env=env_vec,
                verbose=1,
                tensorboard_log=logdir,
                **kwargs
            )

        # Train for a while (logging and saving checkpoints as we go)
        agent.learn(
            total_timesteps=num_steps,
            callback=_cb,
            log_interval=10
        )

    elif alg == 'sac':

        # Default parameters for SAC
        kwargs.setdefault("learning_rate", 1e-4)
        kwargs.setdefault("buffer_size", 1000000)
        kwargs.setdefault("batch_size", 256)
        kwargs.setdefault("ent_coef", 'auto')
        # kwargs.setdefault("ent_coef", 'auto_0.1')

        kwargs.setdefault("action_noise", NormalActionNoise(
            mean=0,
            sigma=0.2,
        ))

        print("Constructing SAC agent with settings:")
        pprint.pprint(kwargs)

        # Construct the agent
        # XXX ajs 14/Sep/19 SAC in stable_baselines uses outdated policy
        # classes so we just use MlpPolicy and pass policy_kwargs

        if load_policy:
            print("Load SAC agent from ", load_policy_dir)
            kwargs.setdefault("policy_kwargs", dict(layers=[350, 250], act_fun=tf.nn.relu))
            agent = SAC.load(load_path=os.path.join(load_policy_dir, "model.final.pkl"),
                             env=env_vec,
                             verbose=1,
                             tensorboard_log=logdir,
                             **kwargs
                             )
        else:
            agent = SAC(
                policy='MlpPolicy',
                env=env_vec,
                verbose=1,
                tensorboard_log=logdir,
                policy_kwargs=dict(layers=[350, 250], act_fun=tf.nn.relu),
                **kwargs
            )

        # Train for a while (logging and saving checkpoints as we go)
        agent.learn(
            total_timesteps=num_steps,
            callback=_cb
        )

    elif alg == 'td3':

        # Default parameters for SAC
        kwargs.setdefault("learning_rate", 1e-4)
        kwargs.setdefault("buffer_size", 1000000)
        kwargs.setdefault("batch_size", 256)
        kwargs.setdefault("gradient_steps", 1000)
        kwargs.setdefault("learning_starts", 10000)
        kwargs.setdefault("train_freq", 1000)

        # kwargs.setdefault("ent_coef", 'auto_0.1')

        kwargs.setdefault("action_noise", NormalActionNoise(
            mean=0,
            sigma=0.2,
        ))

        print("Constructing TD3 agent with settings:")
        pprint.pprint(kwargs)

        # Construct the agent
        # XXX ajs 14/Sep/19 SAC in stable_baselines uses outdated policy
        # classes so we just use MlpPolicy and pass policy_kwargs
        if load_policy:
            print("Load TD3 agent from ", load_policy_dir)
            kwargs.setdefault("policy_kwargs", dict(layers=[350, 250], act_fun=tf.nn.relu))
            agent = TD3.load(load_path=os.path.join(load_policy_dir, "model.final.pkl"),
                             env=env_vec,
                             verbose=1,
                             tensorboard_log=logdir,
                             **kwargs
                             )
        else:
            agent = TD3(
                policy='MlpPolicy',
                env=env_vec,
                verbose=1,
                tensorboard_log=logdir,
                policy_kwargs=dict(layers=[350, 250], act_fun=tf.nn.relu),
                **kwargs
            )

        # Train for a while (logging and saving checkpoints as we go)
        agent.learn(
            total_timesteps=num_steps,
            callback=_cb
        )

    else:
        raise ValueError("Invalid alg: {}".format(alg))

    # Save final model
    agent.save(os.path.join(logdir, 'model.final.pkl'))

    print("Done")


if __name__ == '__main__':
    import os
    import json
    import argparse

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        "--alg",
        type=str,
        choices=('ddpg', 'sac', 'ppo2', 'td3'),
        required=True,
        help="Algorithm to train"
    )

    parser.add_argument(
        "--task",
        type=str,
        required=True,
        help="Task to run"
    )

    parser.add_argument(
        "--logdir",
        type=str,
        required=False,
        default=".",
        help="Logging directory prefix"
    )

    parser.add_argument(
        "--domain",
        type=str,
        required=False,
        default="jitterbug",
        help="Either 'jitterbug' or 'augmented_jitterbug'"
    )

    parser.add_argument(
        "--num_sim",
        type=int,
        required=False,
        default=1,
        help="The number of simulations to run sequentially'"
    )

    parser.add_argument(
        "--kwargs",
        type=json.loads,
        required=False,
        default={},
        help="Agent keyword arguments"
    )

    args = parser.parse_args()
    log = args.logdir
    for i in range(args.num_sim):
        logdir = os.path.join(log, str(i))
        if i == 0:
            load_policy = False
            load_policy_dir = ""
        else:
            # Load policy
            load_policy = True
            load_policy_dir = os.path.join(log, str(i-1))

        train(alg=args.alg,
              task=args.task,
              logdir=logdir,
              domain_name=args.domain,
              load_policy=load_policy,
              load_policy_dir=load_policy_dir,
              **args.kwargs
              )
