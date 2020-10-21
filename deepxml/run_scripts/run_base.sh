#!/bin/bash

train () {
        # $1 model_dir
        # $2 result_dir
        # $3 Extra Parameters
        
        log_tr_file="${2}/log_train.txt"
        python3 -u ${work_dir}/programs/deepxmlpp/deepxml/main.py --model_dir $1 \
                                --result_dir $2 \
                                --mode train \
                                ${3}| tee $log_tr_file
}

retrain () {
        # TODO
        # $1 dataset
        # $2 data_dir
        # $3 model_dir
        # $4 result_dir
        # $5 model_fname
        # $6 batch_size
        # $7 pred_fname
        # $14 extra params

        log_pred_file="${4}/log_predict.txt"
        python3 -u ${work_dir}/programs/deepxmlpp/deepxml/main.py --dataset $1 \
                                --data_dir $2 \
                                --model_dir $3 \
                                --result_dir $4 \
                                --embedding_dims $6 \
                                --batch_size ${12} \
                                --lr $5 \
                                --dlr_step ${11} \
                                --model_fname ${13} \
                                --dlr_factor ${10} \
                                --vocabulary_dims $7 \
                                --num_labels $8 \
                                --num_epochs $9\
                                ${14} |& tee $log_tr_file
}

predict () {
        # $1 result_dir
        # $2 model_dir
        # $3 extra params
        log_pred_file="${1}/log_predict.txt"
        python3 -u ${work_dir}/programs/deepxmlpp/deepxml/main.py --model_dir $2 \
                                --result_dir $1 \
                                --mode predict \
                                ${3} | tee $log_pred_file
}


extract () {
        # $1 result_dir
        # $2 model_dir
        # $3 extra params
        log_pred_file="${1}/log_predict.txt"
        python3 -u ${work_dir}/programs/deepxmlpp/deepxml/main.py --result_dir $1 \
                                --model_dir $2 \
                                --mode extract \
                                ${3} | tee -a $log_pred_file
}


retrain_w_shorty () {
        # $1 model_dir
        # $2 result_dir
        # $3 Extra Parameters
        
        log_tr_file="${2}/log_train_post.txt"
        python3 -u ${work_dir}/programs/deepxmlpp/deepxml/main.py --model_dir $1 \
                                --result_dir $2 \
                                --mode retrain_w_shorty \
                                ${3}| tee $log_tr_file
}

evaluate () {
	# $1 result dir
        # $2 trn labels
        # $3 target labels
        # $4 filter labels
        # $5 pred_fname/path
        # $6 A
        # $7 B
        # $8 SAVE
	# $9 BETAS
        log_eval_file="${1}/log_eval.txt"
        python3 -u ${work_dir}/programs/deepxmlpp/deepxml/tools/evaluate.py "${2}" "${3}" "${4}" $5 $6 $7 $8 $9 | tee -a $log_eval_file
}


# $1 Flag
# $2 dataset
# $3 work directory
# $4 version

FLAG="${1}"
dataset=$2
work_dir=$3
version=$4
model_name=$5
data_dir="${3}/data/${2}"
model_dir="${3}/models/${model_name}/${2}/v_${4}"
result_dir="${3}/results/${model_name}/${2}/v_${4}"
shift 5

mkdir -p $model_dir
mkdir -p $result_dir

if [ "${FLAG}" == "train" ]
then
    # $1 PARAMS
    train $model_dir $result_dir "${1}"
elif [ "${FLAG}" == "predict" ]
then
    # #1 PARAMS
    predict $result_dir $model_dir "${1}"
elif [ "${FLAG}" == "evaluate" ]
then
    # $1 true labels
    # $2 out file
    # $3 filter labels
    # $4 A
    # $5 B
    # $6 save
    # $7 BETAS
    echo "${4} ${5} ${6} ${7}"
    evaluate $result_dir "${data_dir}/trn_X_Y.txt" "${1}" "${3}" "${result_dir}/${2}" ${4} ${5} ${6} "${7}"
elif [ "${FLAG}" == "extract" ]
then
    # $1 PARAMS
    mkdir -p "${result_dir}/export"
    extract $result_dir $model_dir "${1}"
elif [ "${FLAG}" == "retrain_w_shortlist" ]
then
    # $1 embedding files
    # $2 file 
    retrain_w_shorty $model_dir $result_dir "${1}"
else
    echo "Kuch bhi"
fi
