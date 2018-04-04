import torch
import pdb

import numpy as np


def init_state(batch_size, tm_output_units, tm_state_units, n_heads, N, M):
    tm_output = torch.ones((batch_size, tm_output_units))
    tm_state = torch.ones((batch_size, tm_state_units))
    wt = torch.zeros((batch_size, n_heads, N))
    wt[:, :, 0] = 1.0

    mem_t = torch.ones((batch_size, M, N)) * 0.01

    states = [tm_state, wt, mem_t]
    return tm_output, states


def build_data_gen(min_len, max_len, batch_size, bias, element_size, nb_markers_max):
    dummy_size = element_size + 2
    while True:
        # number of markers
        nb_markers = np.random.randint(0, nb_markers_max+1)

        # set the sequence length of each marker
        seq_lengths = np.random.randint(low=min_len, high=max_len + 1, size=nb_markers+1)

        # set the position of markers
        position_markers = tuple(np.cumsum(seq_lengths))
        shift = tuple(np.arange(nb_markers))

        # create the sequence
        seq = np.random.binomial(1, bias, (batch_size, sum(seq_lengths), element_size))

        # Add markers
        if nb_markers != 0:
            seq = np.insert(seq, position_markers[:-1], 0, axis=1)

        # Add two channels
        inputs = np.insert(seq, (0, 0), 0, axis=2)

        # set the channel values of separator
        if nb_markers != 0:
            pos_marker = tuple(map(sum, zip(position_markers[:-1], shift)))
            inputs[:, pos_marker, 1] = 1

        target = seq[:, -seq_lengths[-1]:, :]

        dummy_input = np.zeros((batch_size, seq_lengths[-1], dummy_size))
        dummy_input[:, :, 0] = 1
        inputs = np.concatenate((inputs, dummy_input), axis=1)

        inputs = torch.from_numpy(inputs).float()
        target = torch.from_numpy(target).float()
        #print("seq_length:", seq_lengths)
        #print("nb_markers:", nb_markers)

        yield inputs, target, seq_lengths

#a = build_data_gen(3, 6, 1, 0.5, 8, 5)

#for inputs, target, seq_length in a:
#    print("seq_length", seq_length)
#    print("inputs", inputs)
#    print("target", target)
#    break
