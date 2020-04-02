import tensorflow as tf
from fennlp.models import bert
from fennlp.optimizers import optim
from fennlp.tools import bert_init_weights_from_checkpoint
from fennlp.datas.checkpoint import LoadCheckpoint
from fennlp.datas.dataloader import TFWriter, TFLoader
from fennlp.metrics import Metric, Losess

# 载入参数
load_check = LoadCheckpoint()
param, vocab_file, model_path = load_check.load_bert_param()

# 定制参数
param["batch_size"] = 8
param["maxlen"] = 100
param["label_size"] = 15


# 构建模型
class BERT_NER(tf.keras.Model):
    def __init__(self, param, **kwargs):
        super(BERT_NER, self).__init__(**kwargs)
        self.batch_size = param["batch_size"]
        self.maxlen = param["maxlen"]
        self.label_size = param["label_size"]
        self.bert = bert.BERT(param)
        self.dense = tf.keras.layers.Dense(self.label_size, activation="relu")

    def call(self, inputs, is_training=True):
        bert = self.bert(inputs, is_training)
        sequence_output = bert.get_pooled_output()  # batch,768
        pre = self.dense(sequence_output)
        output = tf.math.softmax(pre, axis=-1)
        return output

    def predict(self, inputs, is_training=False):
        output = self(inputs, is_training=is_training)
        return output


model = BERT_NER(param)

model.build(input_shape=(3, param["batch_size"], param["maxlen"]))

model.summary()

# 构建优化器
optimizer_bert = optim.AdamWarmup(learning_rate=2e-5,  # 重要参数
                                  decay_steps=10000,  # 重要参数
                                  warmup_steps=1000, )
#
# # 构建损失函数
# mask_sparse_categotical_loss = Losess.MaskSparseCategoricalCrossentropy(from_logits=False,use_mask=True)
mask_sparse_categotical_loss = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False)
# # 初始化参数
bert_init_weights_from_checkpoint(model,
                             model_path,
                             param["num_hidden_layers"],
                             pooler=True)

# 写入数据 通过check_exist=True参数控制仅在第一次调用时写入
writer = TFWriter(param["maxlen"], vocab_file,
                    modes=["train"], task='cls', check_exist=False)

load = TFLoader(param["maxlen"], param["batch_size"], task='cls', epoch=5)

# 训练模型
# 使用tensorboard
summary_writer = tf.summary.create_file_writer("./tensorboard")

# Metrics
f1score = Metric.SparseF1Score(average="macro")
precsionscore = Metric.SparsePrecisionScore(average="macro")
recallscore = Metric.SparseRecallScore(average="macro")
accuarcyscore = Metric.SparseAccuracy()

# 保存模型
checkpoint = tf.train.Checkpoint(model=model)
manager = tf.train.CheckpointManager(checkpoint, directory="./save",
                                     checkpoint_name="model.ckpt",
                                     max_to_keep=3)
# For train model
Batch = 0
for X, token_type_id, input_mask, Y in load.load_train():

    with tf.GradientTape() as tape:
        predict = model([X, token_type_id, input_mask])
        loss = mask_sparse_categotical_loss(Y, predict)
        f1 = f1score(Y, predict)
        precision = precsionscore(Y, predict)
        recall = recallscore(Y, predict)
        accuracy = accuarcyscore(Y, predict)
        if Batch % 101 == 0:
            print("Batch:{}\tloss:{:.4f}".format(Batch, loss.numpy()))
            print("Batch:{}\tacc:{:.4f}".format(Batch, accuracy))
            print("Batch:{}\tprecision{:.4f}".format(Batch, precision))
            print("Batch:{}\trecall:{:.4f}".format(Batch, recall))
            print("Batch:{}\tf1score:{:.4f}".format(Batch, f1))
            manager.save(checkpoint_number=Batch)

        with summary_writer.as_default():
            tf.summary.scalar("loss", loss, step=Batch)
            tf.summary.scalar("acc", accuracy, step=Batch)
            tf.summary.scalar("f1", f1, step=Batch)
            tf.summary.scalar("precision", precision, step=Batch)
            tf.summary.scalar("recall", recall, step=Batch)

    grads_bert = tape.gradient(loss, model.variables)
    optimizer_bert.apply_gradients(grads_and_vars=zip(grads_bert, model.variables))
    Batch += 1