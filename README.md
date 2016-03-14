## POS-Tagging-benchmark
- Theano
- Chainer
- Merlin

## Data
* Penn Treebank
 - Training: section 00-18 ("wsj_00-18.conll")
 - Testing: section 22-24 ("wsj_22-24.conll")
* Word list ("words.lst")
* Word embeddings ("nyt100.lst")

## Network Structure
```
function forward(words)
  for i=1:#words
    char_vectors[i] =
      words[i].chars [1*#chars] ->
      embed(10) [10*#chars] ->
      conv2d(linear=(50, 50), filter_size=(10,5), stride=(1,1), pad_size=(10,2)) [50*#chars] ->
      max(dim=2) [50*1]
  end
  char_matrix = char_vectors -> concat(2) [50*#words]
  
  word_matrix = words [1*#words] -> embed(100) [100*#words]
  
  sent_matrix = [char_matrix, word_matrix] -> concat(1) [150*#words]
  
  out_matrix =
    sent_matrix ->
    conv2d(linear=(750,300), filter_size=(150,5), stride=(1,1), pad_size=(150,2)) [300*#words] ->
    relu [300*#words] ->
    linear(300,45) [45*#words]
end
```

## Settings
* word preprocessing: [token.jl](https://github.com/hshindo/Merlin.jl/blob/master/examples/postagging/token.jl)
* lookup initialization: [lookup.jl](https://github.com/hshindo/Merlin.jl/blob/master/src/functors/lookup.jl)
* linear initialization: [linear.jl](https://github.com/hshindo/Merlin.jl/blob/master/src/functors/linear.jl)

## Training
- SGD (learning rate: 0.0075 / # iter)
- Loss function: cross-entropy
- #epochs: 10

## Results
### Setting 1
* train: first 5000 sentences in training data
* test: all sentences in test data
* [result5000-update_embed]()
* [result5000-noupdate_embed]()

### Setting 2
