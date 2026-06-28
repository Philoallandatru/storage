SSD_NAME=Biwin
CACHE=./mnt/kvssd

 python kv-cache.py \
  --config config.yaml \
  --model qwen3-32b \
  --dataset-path ShareGPT_V3_unfiltered_cleaned_split.json \
  --max-conversations 1000 \
  --num-users 100 \
  --duration 600 \
  --gpu-mem-gb 32 \
  --cpu-mem-gb 64 \
  --max-concurrent-allocs 16 \
  --generation-mode realistic \
  --cache-dir ${CACHE} \
  --seed 42 \
  --output results/${SSD_NAME}_sharegpt_qwen32b.json \
  --xlsx-output results/${SSD_NAME}_sharegpt_qwen32b.xlsx
