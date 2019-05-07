"""A Jitterbug dm_control Reinforcement Learning domain

Copyright 2018 The authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import sys
import inspect
import collections

import numpy as np

from dm_control import mujoco
from dm_control.rl import control
from dm_control.suite import base
from dm_control.suite import common
from dm_control.utils import rewards
from dm_control.utils import containers
from dm_control.utils import io as resources
from dm_control.mujoco.wrapper.mjbindings import mjlib


# Load the suite so we can add to it
SUITE = containers.TaggedTasks()

# Environment constants
DEFAULT_TIME_LIMIT = 10
DEFAULT_CONTROL_TIMESTEP = 0.01

def get_model_and_assets():
    """Returns a tuple containing the model XML string and a dict of assets"""
    return (
        resources.GetResource(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "jitterbug.xml"
        )),
        common.ASSETS
    )


@SUITE.add("benchmarking", "easy")
def move_from_origin(
        time_limit=DEFAULT_TIME_LIMIT,
        control_timestep=DEFAULT_CONTROL_TIMESTEP,
        random=None,
        environment_kwargs=None
):
    """Move the Jitterbug away from the origin"""
    physics = Physics.from_xml_string(*get_model_and_assets())
    task = Jitterbug(random=random, task="move_from_origin")
    environment_kwargs = environment_kwargs or {}
    return control.Environment(
        physics,
        task,
        time_limit=time_limit,
        control_timestep=control_timestep,
        **environment_kwargs
    )


@SUITE.add("benchmarking", "easy")
def face_direction(
        time_limit=DEFAULT_TIME_LIMIT,
        control_timestep=DEFAULT_CONTROL_TIMESTEP,
        random=None,
        environment_kwargs=None
):
    """Move the Jitterbug to face a certain yaw angle"""
    physics = Physics.from_xml_string(*get_model_and_assets())
    task = Jitterbug(random=random, task="face_direction")
    environment_kwargs = environment_kwargs or {}
    return control.Environment(
        physics,
        task,
        time_limit=time_limit,
        control_timestep=control_timestep,
        **environment_kwargs
    )

@SUITE.add("benchmarking", "easy")
def move_in_direction(
        time_limit=DEFAULT_TIME_LIMIT,
        control_timestep=DEFAULT_CONTROL_TIMESTEP,
        random=None,
        environment_kwargs=None
):
    """Move the Jitterbug in a certain direction"""
    physics = Physics.from_xml_string(*get_model_and_assets())
    task = Jitterbug(random=random, task="move_in_direction")
    environment_kwargs = environment_kwargs or {}
    return control.Environment(
        physics,
        task,
        time_limit=time_limit,
        control_timestep=control_timestep,
        **environment_kwargs
    )


@SUITE.add("benchmarking", "hard")
def move_to_position(
        time_limit=DEFAULT_TIME_LIMIT,
        control_timestep=DEFAULT_CONTROL_TIMESTEP,
        random=None,
        environment_kwargs=None
):
    """Move the Jitterbug to a certain XYZ position"""
    physics = Physics.from_xml_string(*get_model_and_assets())
    task = Jitterbug(random=random, task="move_to_position")
    environment_kwargs = environment_kwargs or {}
    return control.Environment(
        physics,
        task,
        time_limit=time_limit,
        control_timestep=control_timestep,
        **environment_kwargs
    )


@SUITE.add("benchmarking", "hard")
def move_to_pose(
        time_limit=DEFAULT_TIME_LIMIT,
        control_timestep=DEFAULT_CONTROL_TIMESTEP,
        random=None,
        environment_kwargs=None
):
    """Move the Jitterbug to a certain XYZRPY pose"""
    physics = Physics.from_xml_string(*get_model_and_assets())
    task = Jitterbug(random=random, task="move_to_pose")
    environment_kwargs = environment_kwargs or {}
    return control.Environment(
        physics,
        task,
        time_limit=time_limit,
        control_timestep=control_timestep,
        **environment_kwargs
    )


class Physics(mujoco.Physics):
    """Physics simulation with additional features"""

    def jitterbug_position(self):
        """Get the full jitterbug pose vector"""
        return self.named.data.qpos["root"]

    def jitterbug_position_xyz(self):
        """Get the XYZ position of the Jitterbug"""
        return self.jitterbug_position()[:3]

    def jitterbug_position_quat(self):
        """Get the orientation of the Jitterbug"""
        return self.jitterbug_position()[3:]

    def jitterbug_direction_yaw(self):
        """Get the yaw angle of the Jitterbug in radians

        Returns:
            (float): Yaw angle of the Jitterbug in radians on the range
                [-pi, pi]
        """
        mat = np.zeros((9))
        mjlib.mju_quat2Mat(mat, self.jitterbug_position_quat())
        mat = mat.reshape((3, 3))
        yaw = np.arctan2(mat[1, 0], mat[0, 0])

        # Jitterbug model faces the -Y direction, so we rotate 90deg CW to
        # align its face with the +X axis
        yaw -= np.pi / 2

        return yaw

    def jitterbug_velocity(self):
        """Get the full jitterbug velocity vector"""
        return self.named.data.qvel["root"]

    def jitterbug_velocity_xyz(self):
        """Get the XYZ velocity of the Jitterbug"""
        return self.jitterbug_velocity()[:3]

    def jitterbug_velocity_rpy(self):
        """Get the angular velocity of the Jitterbug"""
        return self.jitterbug_velocity()[3:]

    def motor_position(self):
        """Get the motor angular position"""
        return self.named.data.qpos["jointMass"]

    def motor_velocity(self):
        """Get the motor angular velocity"""
        return self.named.data.qvel["jointMass"]

    def target_position(self):
        """Get the full target pose vector"""
        return np.concatenate((
                self.target_position_xyz(),
                self.target_position_quat()
            ),
            axis=0
        )

    def target_position_xyz(self):
        """Get the XYZ position of the target"""
        return self.named.data.geom_xpos["target"]

    def target_position_quat(self):
        """Get the orientation of the target"""
        return self.named.data.xquat["target"]

    def target_direction_yaw(self):
        """Get the yaw angle of the target in radians

        Returns:
            (float): Yaw angle of the target in radians on the range
                [-pi, pi]
        """
        mat = np.zeros((9))
        mjlib.mju_quat2Mat(mat, self.target_position_quat())
        mat = mat.reshape((3, 3))
        yaw = np.arctan2(mat[1, 0], mat[0, 0])
        return yaw

    def target_direction_vec2(self):
        """Get the target heading as a global 2-vector"""
        target_yaw = self.target_direction_yaw()
        return np.array([
            np.cos(target_yaw),
            np.sin(target_yaw)
        ])

    def vec3_jitterbug_to_target(self):
        """Gets an XYZ vector from jitterbug to the target"""
        return self.target_position_xyz() - self.jitterbug_position_xyz()

    def angle_jitterbug_to_target(self):
        """Gets the relative yaw angle from Jitterbug heading to the target

        Returns:
            (float): The relative angle in radians from the target to the
                Jitterbug on the range [-pi, pi]
        """
        angle = self.target_direction_yaw() - self.jitterbug_direction_yaw()
        while angle > np.pi:
            angle -= 2*np.pi
        while angle <= -np.pi:
            angle += 2*np.pi
        return angle

    def vec2_direction_to_target(self):
        """Get the relative XY yaw direction vector to the target"""
        target_yaw = self.angle_jitterbug_to_target()
        return np.array([
            np.cos(target_yaw),
            np.sin(target_yaw)
        ])


class Jitterbug(base.Task):
    """A jitterbug `Task`"""

    def __init__(self, random=None, task="move_from_origin"):
        """Initialize an instance of the `Jitterbug` domain

        Args:
            random (numpy.random.RandomState): Options are;
                - numpy.random.RandomState instance
                - An integer seed for creating a new `RandomState`
                - None to select a seed automatically (default)
            task (str): Specifies which task to configure. Options are;
                - move_from_origin
                - face_direction
                - move_in_direction
                - move_to_position
                - move_to_pose
        """

        # Reflect to get task names from the current module
        self.task_names = [
            obj[0]
            for obj in inspect.getmembers(sys.modules[__name__])
            if inspect.isfunction(obj[1]) and obj[0] in SUITE._tasks
        ]
        assert task in self.task_names,\
            "Invalid task {}, options are {}".format(task, self.task_names)

        self.task = task
        super(Jitterbug, self).__init__(random=random)

    def initialize_episode(self, physics):
        """Sets the state of the environment at the start of each episode
        """

        # Use reset context to ensure changes are applied immediately
        with physics.reset_context():

            # Configure target based on task
            angle = self.random.uniform(0, 2 * np.pi)
            radius = self.random.uniform(.05, 0.3)
            yaw = np.random.uniform(0, 2 * np.pi)

            if self.task == "move_from_origin":

                # Hide the target orientation as it is not needed for this task
                physics.named.model.geom_rgba["targetPointer", 3] = 0

            elif self.task == "face_direction":

                # Randomize target orientation
                physics.named.model.body_quat["target"] = np.array([
                    np.cos(yaw / 2), 0, 0, 1 * np.sin(yaw / 2)
                ])

            elif self.task == "move_in_direction":

                # Randomize target orientation
                physics.named.model.body_quat["target"] = np.array([
                    np.cos(yaw / 2), 0, 0, 1 * np.sin(yaw / 2)
                ])

            elif self.task == "move_to_position":

                # Hide the target orientation indicator as it is not needed
                physics.named.model.geom_rgba["targetPointer", 3] = 0

                # Randomize target position
                physics.named.model.body_pos["target", "x"] = radius * np.sin(angle)
                physics.named.model.body_pos["target", "y"] = radius * np.cos(angle)

            elif self.task == "move_to_pose":

                # Randomize full target pose
                physics.named.model.body_pos["target", "x"] = radius * np.sin(angle)
                physics.named.model.body_pos["target", "y"] = radius * np.cos(angle)
                physics.named.model.body_quat["target"] = np.array([
                    np.cos(yaw / 2), 0, 0, 1 * np.sin(yaw / 2)
                ])

            else:
                raise ValueError("Invalid task {}".format(self.task))

        super(Jitterbug, self).initialize_episode(physics)

    def get_observation(self, physics):
        """Returns an observation of the state and the target position
        """

        obs = collections.OrderedDict()
        obs['position'] = physics.jitterbug_position()
        obs['velocity'] = physics.jitterbug_velocity()
        obs['motor_position'] = physics.motor_position()
        obs['motor_velocity'] = physics.motor_velocity()

        if self.task == "move_from_origin":

            # Jitterbug position is a sufficient observation for this task
            pass

        elif self.task == "face_direction":

            # Store the relative target direction vector
            obs['target_direction'] = physics.vec2_direction_to_target()

        elif self.task == "move_in_direction":

            # Store the relative target direction vector
            obs['target_direction'] = physics.vec2_direction_to_target()

        elif self.task == "move_to_position":

            # Store the relative target XYZ position
            obs['target_position'] = physics.vec3_jitterbug_to_target()

        elif self.task == "move_to_pose":

            # Store the relative target XYZ position
            obs['target_position'] = physics.vec3_jitterbug_to_target()

            # Store the relative target direction vector
            obs['target_direction'] = physics.vec2_direction_to_target()

        else:
            raise ValueError("Invalid task {}".format(self.task))

        return obs

    def face_direction_reward(self, physics):
        """Compute a reward for facing a certain direction

        See https://www.desmos.com/calculator/iaczzkaplq for a plot of the
        reward function.

        Returns:
            (float): Angular reward on [0, 1] as you face the target direction
        """
        angle_to_target = physics.angle_jitterbug_to_target()
        return 2 / (np.abs(angle_to_target) / np.pi + 1) - 1

    def move_to_position_reward(self, physics):
        """Compute a reward for moving to a certain position

        See https://www.desmos.com/calculator/cppbhrtxlj for a plot of the
        reward function.

        Returns:
            (float): Position reward on [0, 1], grows larger as you approach the
                the goal, asymptoting to 0 at an infinite distance
        """
        dist_to_target = np.linalg.norm(physics.vec3_jitterbug_to_target())
        return 1 / (10 * dist_to_target + 1)

    def upright_reward(self, physics):
        """Reward Jitterbug for remaining upright"""
        return min(
            max(
                0,
                # Dot product of the Jitterbug Z axis with the global Z
                physics.named.data.xmat['jitterbug', 'zz']
            ),
            1
        )

    def get_reward(self, physics):

        r = 0

        if self.task == "move_from_origin":

            r = (1 - self.move_to_position_reward(physics))

        elif self.task == "face_direction":

            r = self.face_direction_reward(physics)

        elif self.task == "move_in_direction":

            # Jitterbug is rewarded for moving in a given target direction
            max_speed_per_step = 0.3
            jitterbug_vel = physics.jitterbug_velocity_xyz()[0:2]
            target_vel = 1.0 * physics.target_direction_vec2()

            r = min(
                max(
                    0.0,
                    jitterbug_vel @ target_vel
                ) / max_speed_per_step,
                1.0
            )

        elif self.task == "move_to_position":

            r = self.move_to_position_reward(physics)

        elif self.task == "move_to_pose":

            # # Use mean reward
            # r = 0.5 * (
            #     self.move_to_position_reward(physics) +
            #     self.face_direction_reward(physics)
            # )

            # Use multiplicitive reward
            r = (
                self.move_to_position_reward(physics) *
                self.face_direction_reward(physics)
            )

        else:
            raise ValueError("Invalid task {}".format(self.task))

        # Reward Jitterbug for staying upright
        r *= self.upright_reward(physics)

        return r


def demo():
    """Demonstrate the Jitterbug domain"""

    # Get some imports
    from dm_control import suite
    from dm_control import viewer

    # Add the jitterbug tasks to the suite
    import jitterbug_dmc

    # Load the Jitterbug face_direction task
    env = suite.load(
        domain_name="jitterbug",
        task_name="face_direction",
        visualize_reward=True
    )

    # Use a constant policy
    policy = lambda ts: -0.8

    # Dance, jitterbug, dance!
    viewer.launch(env, policy=policy)


if __name__ == '__main__':
    demo()
