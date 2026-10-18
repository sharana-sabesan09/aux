# datasets/

Drop your JSONL files here, or register a public Hugging Face dataset with `veri datasets`.

## Upload a local JSONL

```bash
veri datasets upload datasets/train.jsonl --name my-train
```

`upload` auto-runs a structural check (valid JSON objects, row count, duplicate IDs).
Use `--skip-validation` to upload anyway.

## Connect a public Hugging Face dataset without uploading

```bash
veri datasets connect-hf openai/gsm8k --config main --split train --map question=prompt --name gsm8k-train
```

## Reference a dataset in configs/train.toml

```toml
[dataset]
id = "gsm8k-train"   # a registered dataset's name or id
```
