test:
	PYTHONPATH=src python -m unittest discover -s tests -v

run-sample:
	PYTHONPATH=src python -m signalpost --input input.sample.txt --output output/results.jsonl
