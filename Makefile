test:
	python -m unittest discover -s tests -v

run-sample:
	python -m signalpost --input input.sample.txt --output output/results.jsonl
