# Force MKL (CPU BLAS) to use one core, faster
import logging
import logging.config
import os
os.environ["OMP_NUM_THREADS"] = '1'

import yaml
import os.path
from shutil import copyfile
from datetime import datetime
import argparse
import torch
from torch import nn
import torch.nn.functional as F
import collections
import numpy as np

import matplotlib
logging.getLogger("matplotlib").setLevel(logging.WARNING)

# Import problems and problem factory.
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), 'problems'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'models'))
from problems.problem_factory import ProblemFactory
from models.model_factory import ModelFactory

if __name__ == '__main__':

    # Create parser with list of  runtime arguments.
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-t', type=str, default='', dest='task',
                        help='Name of the task configuration file to be loaded')
    parser.add_argument('--tensorboard', action='store', dest='tensorboard', choices=[0, 1, 2], type=int,
                        help="If present, log to tensorboard. Log levels:\n"
                             "0: Just log the loss, accuracy, and seq_len\n"
                             "1: Add histograms of biases and weights (Warning: slow)\n"
                             "2: Add histograms of biases and weights gradients (Warning: even slower)")
    parser.add_argument('--confirm', action='store_true', dest='confirm',
                        help='Request user confirmation just after loading the settings, before starting training.')
    # Parse arguments.
    FLAGS, unparsed = parser.parse_known_args()

    # Check if config file was selected.
    if (FLAGS.task == ''):
        print('Please pass task configuration file as -t parameter')
        exit(-1)
    # Check it file exists.
    if not os.path.isfile(FLAGS.task):
        print('Task configuration file {} does not exists'.format(FLAGS.task))
        exit(-2)

    # Read YAML file
    with open(FLAGS.task, 'r') as stream:
        config_loaded = yaml.load(stream)

    task_name = config_loaded['problem_train']['name']

    # Prepare output paths for logging
    path_root = "./checkpoints/"
    time_str = '{0:%Y%m%d_%H%M%S}'.format(datetime.now())
    log_dir = path_root + task_name + '/' + time_str + '/'
    os.makedirs(log_dir, exist_ok=False)
    log_file = log_dir + 'msgs.log'
    copyfile(FLAGS.task, log_dir + "/train_settings.yaml")  # Copy the task's yaml file into log_dir

    def logfile():
        return logging.FileHandler(log_file)

    with open('logger_config.yaml', 'rt') as f:
        config = yaml.load(f.read())
        logging.config.dictConfig(config)

    logger = logging.getLogger(task_name)

    # print experiment configuration
    str = "Experiment Configuration:\n"
    str += yaml.safe_dump(config_loaded, default_flow_style=False,
                          explicit_start=True, explicit_end=True)
    logger.info(str)

    if FLAGS.confirm:
        # Ask for confirmation
        input('Press any key to continue')

    # set seed
    if config_loaded["settings"]["seed_torch"] != -1:
        torch.manual_seed(config_loaded["settings"]["seed_torch"])

    if config_loaded["settings"]["seed_numpy"] != -1:
        np.random.seed(config_loaded["settings"]["seed_numpy"])

    # Determine if CUDA is to be used
    use_CUDA = False
    if torch.cuda.is_available():
        try:  # If the 'cuda' key is not present, catch the exception and do nothing
            if config_loaded['problem_train']['cuda']:
                use_CUDA = True
        except KeyError:
            None

    # Build problem
    problem = ProblemFactory.build_problem(config_loaded['problem_train'])

    # Build model
    model = ModelFactory.build_model(config_loaded['model'])
    model.cuda() if use_CUDA else None

    # Set loss and optimizer
    optimizer_conf = dict(config_loaded['optimizer'])
    optimizer_name = optimizer_conf['name']
    del optimizer_conf['name']

    criterion = nn.BCEWithLogitsLoss()
    optimizer = getattr(torch.optim, optimizer_name)(model.parameters(), **optimizer_conf)

    # Create tensorboard output, if tensorboard chosen
    if FLAGS.tensorboard is not None:
        from tensorboardX import SummaryWriter
        tb_writer = SummaryWriter(log_dir)

    # Start Training
    epoch = 0
    last_losses = collections.deque()

    train_file = open(log_dir + 'training.log', 'w', 1)
    validation_file = open(log_dir + 'validation.log', 'w', 1)
    train_file.write('epoch,accuracy,loss,length\n')
    validation_file.write('epoch,accuracy\n')

    # Data generator : input & target
    for inputs, targets, mask in problem.return_generator():
        # Convert inputs and targets to CUDA
        if use_CUDA:
            inputs = inputs.cuda()
            targets = targets.cuda()

        optimizer.zero_grad()

        # apply model
        output = model(inputs)

        # compute loss
        # TODO: solution for now - mask[0]
        if config_loaded['settings']['use_mask']:
            output = output[:, mask[0], :]
            targets = targets[:, mask[0], :]

        loss = criterion(output, targets)

        # append the new loss
        last_losses.append(loss)
        if len(last_losses) > config_loaded['settings']['length_loss']:
            last_losses.popleft()

        loss.backward()

        # clip grad between -10, 10
        nn.utils.clip_grad_value_(model.parameters(), 10)

        optimizer.step()

        # print statistics
        accuracy = (1 - torch.abs(torch.round(F.sigmoid(output)) - targets)).mean()
        train_length = inputs.size(-2)
        format_str = 'epoch {:05d}: '
        format_str = format_str + ' acc={:12.10f}; loss={:12.10f}; length={:02d}'
        logger.info(format_str.format(epoch, accuracy, loss, train_length))
        format_str = '{:05d}, {:12.10f}, {:12.10f}, {:02d}\n'
        train_file.write(format_str.format(epoch, accuracy, loss, train_length))

        if FLAGS.tensorboard is not None:
            # Save loss + accuracy to tensorboard
            accuracy = (1 - torch.abs(torch.round(F.sigmoid(output)) - targets)).mean()
            tb_writer.add_scalar('Train/loss', loss, epoch)
            tb_writer.add_scalar('Train/accuracy', accuracy, epoch)
            tb_writer.add_scalar('Train/seq_len', train_length, epoch)

            for name, param in model.named_parameters():
                if FLAGS.tensorboard >= 1:
                    tb_writer.add_histogram(name, param.data.cpu().numpy(), epoch)
                if FLAGS.tensorboard >= 2:
                    tb_writer.add_histogram(name + '/grad', param.grad.data.cpu().numpy(), epoch)

        if max(last_losses) < config_loaded['settings']['loss_stop'] \
                or epoch == config_loaded['settings']['max_epochs']:
            # save model parameters
            torch.save(model.state_dict(), log_dir + "/model_parameters")
            break

        epoch += 1

    train_file.close()
    validation_file.close()

    print("Learning finished!")
