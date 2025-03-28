# Copyright 2020 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# maxlengthations under the License.
# ==============================================================================
"""Tests for bincount ops."""

from absl.testing import parameterized
import numpy as np

from tensorflow.python.framework import errors
from tensorflow.python.framework import ops
from tensorflow.python.framework import sparse_tensor
from tensorflow.python.framework import test_util
from tensorflow.python.ops import bincount_ops
from tensorflow.python.ops import gen_count_ops
from tensorflow.python.ops import sparse_ops
from tensorflow.python.platform import test


class TestDenseBincount(test.TestCase, parameterized.TestCase):

  @parameterized.parameters([{
      "dtype": np.int32,
  }, {
      "dtype": np.int64,
  }])
  def test_sparse_input_all_count(self, dtype):
    np.random.seed(42)
    num_rows = 4096
    size = 1000
    n_elems = 128
    inp_indices = np.random.randint(0, num_rows, (n_elems, 1))
    inp_indices = np.concatenate([inp_indices, np.zeros((n_elems, 1))], axis=1)
    inp_vals = np.random.randint(0, size, (n_elems,), dtype=dtype)
    sparse_inp = sparse_tensor.SparseTensor(inp_indices, inp_vals,
                                            [num_rows, 1])

    # Note that the result for a sparse tensor is the same as for the
    # equivalent dense tenor, i.e. implicit zeros are counted.
    np_out = np.bincount(inp_vals, minlength=size)
    implict_zeros = num_rows - n_elems
    np_out[0] += implict_zeros
    self.assertAllEqual(
        np_out,
        self.evaluate(
            bincount_ops.bincount(sparse_inp, axis=0, minlength=size)
        ),
    )

  @parameterized.parameters([{
      "dtype": np.int32,
  }, {
      "dtype": np.int64,
  }])
  def test_sparse_input_all_count_with_weights(self, dtype):
    np.random.seed(42)
    num_rows = 4096
    size = 1000
    n_elems = 128
    inp_indices = np.random.randint(0, num_rows, (n_elems, 1))
    inp_indices = np.concatenate([inp_indices, np.zeros((n_elems, 1))], axis=1)
    inp_vals = np.random.randint(0, size, (n_elems-1,), dtype=dtype)
    # Add an element with value `size-1` to input so bincount output has `size`
    # elements.
    inp_vals = np.concatenate([inp_vals, [size-1]], axis=0)
    sparse_inp = sparse_tensor.SparseTensor(inp_indices, inp_vals,
                                            [num_rows, 1])
    weight_vals = np.random.random((n_elems,))
    sparse_weights = sparse_tensor.SparseTensor(inp_indices, weight_vals,
                                                [num_rows, 1])

    np_out = np.bincount(inp_vals, minlength=size, weights=weight_vals)
    self.assertAllEqual(
        np_out,
        self.evaluate(bincount_ops.bincount(
            sparse_inp, sparse_weights, axis=0)))

  @parameterized.parameters([{
      "dtype": np.int32,
  }, {
      "dtype": np.int64,
  }])
  def test_sparse_input_all_binary(self, dtype):
    np.random.seed(42)
    num_rows = 4096
    size = 10
    n_elems = 128
    inp_indices = np.random.randint(0, num_rows, (n_elems, 1))
    inp_indices = np.concatenate([inp_indices, np.zeros((n_elems, 1))], axis=1)
    inp_vals = np.random.randint(0, size, (n_elems,), dtype=dtype)
    sparse_inp = sparse_tensor.SparseTensor(inp_indices, inp_vals,
                                            [num_rows, 1])

    np_out = np.ones((size,))
    self.assertAllEqual(
        np_out,
        self.evaluate(bincount_ops.bincount(sparse_inp, binary_output=True)))

  @parameterized.parameters([{
      "dtype": np.int32,
  }, {
      "dtype": np.int64,
  }])
  def test_sparse_input_col_reduce_count(self, dtype):
    num_rows = 128
    num_cols = 27
    size = 100
    np.random.seed(42)
    inp = np.random.randint(0, size, (num_rows, num_cols), dtype=dtype)
    np_out = np.reshape(
        np.concatenate(
            [np.bincount(inp[j, :], minlength=size) for j in range(num_rows)],
            axis=0), (num_rows, size))
    # from_dense will filter out 0s.
    inp = inp + 1
    # from_dense will cause OOM in GPU.
    with ops.device("/CPU:0"):
      inp_sparse = sparse_ops.from_dense(inp)
      inp_sparse = sparse_tensor.SparseTensor(inp_sparse.indices,
                                              inp_sparse.values - 1,
                                              inp_sparse.dense_shape)
    self.assertAllEqual(
        np_out, self.evaluate(bincount_ops.bincount(arr=inp_sparse, axis=-1)))

  @parameterized.parameters([{
      "dtype": np.int32,
  }, {
      "dtype": np.int64,
  }])
  def test_sparse_input_col_reduce_binary(self, dtype):
    num_rows = 128
    num_cols = 27
    size = 100
    np.random.seed(42)
    inp = np.random.randint(0, size, (num_rows, num_cols), dtype=dtype)
    np_out = np.reshape(
        np.concatenate([
            np.where(np.bincount(inp[j, :], minlength=size) > 0, 1, 0)
            for j in range(num_rows)
        ],
                       axis=0), (num_rows, size))
    # from_dense will filter out 0s.
    inp = inp + 1
    # from_dense will cause OOM in GPU.
    with ops.device("/CPU:0"):
      inp_sparse = sparse_ops.from_dense(inp)
      inp_sparse = sparse_tensor.SparseTensor(inp_sparse.indices,
                                              inp_sparse.values - 1,
                                              inp_sparse.dense_shape)
    self.assertAllEqual(
        np_out,
        self.evaluate(
            bincount_ops.bincount(arr=inp_sparse, axis=-1, binary_output=True)))


class RawOpsHeapOobTest(test.TestCase, parameterized.TestCase):

  @test_util.run_v1_only("Test security error")
  def testSparseCountSparseOutputBadIndicesShapeTooSmall(self):
    indices = [1]
    values = [[1]]
    weights = []
    dense_shape = [10]
    with self.assertRaisesRegex(ValueError,
                                "Shape must be rank 2 but is rank 1 for"):
      self.evaluate(
          gen_count_ops.SparseCountSparseOutput(
              indices=indices,
              values=values,
              dense_shape=dense_shape,
              weights=weights,
              binary_output=True))


@test_util.run_all_in_graph_and_eager_modes
@test_util.disable_tfrt
class RawOpsTest(test.TestCase, parameterized.TestCase):

  def testSparseCountSparseOutputBadIndicesShape(self):
    indices = [[[0], [0]], [[0], [1]], [[1], [0]], [[1], [2]]]
    values = [1, 1, 1, 10]
    weights = [1, 2, 4, 6]
    dense_shape = [2, 3]
    with self.assertRaisesRegex(errors.InvalidArgumentError,
                                "Input indices must be a 2-dimensional tensor"):
      self.evaluate(
          gen_count_ops.SparseCountSparseOutput(
              indices=indices,
              values=values,
              dense_shape=dense_shape,
              weights=weights,
              binary_output=False))

  def testSparseCountSparseOutputBadWeightsShape(self):
    indices = [[0, 0], [0, 1], [1, 0], [1, 2]]
    values = [1, 1, 1, 10]
    weights = [1, 2, 4]
    dense_shape = [2, 3]
    with self.assertRaisesRegex(errors.InvalidArgumentError,
                                "Weights and values must have the same shape"):
      self.evaluate(
          gen_count_ops.SparseCountSparseOutput(
              indices=indices,
              values=values,
              dense_shape=dense_shape,
              weights=weights,
              binary_output=False))

  def testSparseCountSparseOutputBadNumberOfValues(self):
    indices = [[0, 0], [0, 1], [1, 0]]
    values = [1, 1, 1, 10]
    weights = [1, 2, 4, 6]
    dense_shape = [2, 3]
    with self.assertRaisesRegex(
        errors.InvalidArgumentError,
        "Number of values must match first dimension of indices"):
      self.evaluate(
          gen_count_ops.SparseCountSparseOutput(
              indices=indices,
              values=values,
              dense_shape=dense_shape,
              weights=weights,
              binary_output=False))

  def testSparseCountSparseOutputNegativeValue(self):
    indices = [[0, 0], [0, 1], [1, 0], [1, 2]]
    values = [1, 1, -1, 10]
    dense_shape = [2, 3]
    with self.assertRaisesRegex(errors.InvalidArgumentError,
                                "Input values must all be non-negative"):
      self.evaluate(
          gen_count_ops.SparseCountSparseOutput(
              indices=indices,
              values=values,
              dense_shape=dense_shape,
              binary_output=False))

  def testRaggedCountSparseOutput(self):
    splits = [0, 4, 7]
    values = [1, 1, 2, 1, 2, 10, 5]
    weights = [1, 2, 3, 4, 5, 6, 7]
    output_indices, output_values, output_shape = self.evaluate(
        gen_count_ops.RaggedCountSparseOutput(
            splits=splits, values=values, weights=weights, binary_output=False))
    self.assertAllEqual([[0, 1], [0, 2], [1, 2], [1, 5], [1, 10]],
                        output_indices)
    self.assertAllEqual([7, 3, 5, 7, 6], output_values)
    self.assertAllEqual([2, 11], output_shape)

  def testRaggedCountSparseOutputBadWeightsShape(self):
    splits = [0, 4, 7]
    values = [1, 1, 2, 1, 2, 10, 5]
    weights = [1, 2, 3, 4, 5, 6]
    with self.assertRaisesRegex(errors.InvalidArgumentError,
                                "Weights and values must have the same shape"):
      self.evaluate(
          gen_count_ops.RaggedCountSparseOutput(
              splits=splits,
              values=values,
              weights=weights,
              binary_output=False))

  def testRaggedCountSparseOutputEmptySplits(self):
    splits = []
    values = [1, 1, 2, 1, 2, 10, 5]
    weights = [1, 2, 3, 4, 5, 6, 7]
    with self.assertRaisesRegex(
        errors.InvalidArgumentError,
        "Must provide at least 2 elements for the splits argument"):
      self.evaluate(
          gen_count_ops.RaggedCountSparseOutput(
              splits=splits,
              values=values,
              weights=weights,
              binary_output=False))

  def testRaggedCountSparseOutputBadSplitsStart(self):
    splits = [1, 7]
    values = [1, 1, 2, 1, 2, 10, 5]
    weights = [1, 2, 3, 4, 5, 6, 7]
    with self.assertRaisesRegex(errors.InvalidArgumentError,
                                "Splits must start with 0"):
      self.evaluate(
          gen_count_ops.RaggedCountSparseOutput(
              splits=splits,
              values=values,
              weights=weights,
              binary_output=False))

  def testRaggedCountSparseOutputBadSplitsEnd(self):
    splits = [0, 5]
    values = [1, 1, 2, 1, 2, 10, 5]
    weights = [1, 2, 3, 4, 5, 6, 7]
    with self.assertRaisesRegex(errors.InvalidArgumentError,
                                "Splits must end with the number of values"):
      self.evaluate(
          gen_count_ops.RaggedCountSparseOutput(
              splits=splits,
              values=values,
              weights=weights,
              binary_output=False))

  def testRaggedCountSparseOutputNegativeValue(self):
    splits = [0, 4, 7]
    values = [1, 1, 2, 1, -2, 10, 5]
    with self.assertRaisesRegex(errors.InvalidArgumentError,
                                "Input values must all be non-negative"):
      self.evaluate(
          gen_count_ops.RaggedCountSparseOutput(
              splits=splits, values=values, binary_output=False))


if __name__ == "__main__":
  test.main()
