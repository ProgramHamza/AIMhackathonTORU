"""Run bounded Gemini extraction on selected independent inputs. Never loads gold labels."""
import argparse
import json
from pathlib import Path
import time

from dotenv import load_dotenv
from prep.llm.gemini import GeminiClient
from prep.preparation import prepare_patient, write_bundle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',type=Path,default=Path('tests/fixtures/independent/inputs'))
    parser.add_argument('--case',action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-calls',type=int,default=12)
    args=parser.parse_args()
    directories=[]
    for case in args.case:
        directory=(args.inputs/case).resolve()
        if directory.parent != args.inputs.resolve() or not directory.is_dir():
            parser.error('Case must name a direct child input directory')
        directories.append((case,directory))
    if args.max_calls < 1:
        parser.error('max-calls must be positive')
    load_dotenv(Path(__file__).resolve().parents[1]/'.env.local',override=False)
    client=GeminiClient.from_env()
    client.max_calls=args.max_calls
    started=time.perf_counter()
    cases=[]
    try:
        for case,directory in directories:
            bundle=prepare_patient(directory,case,'independent_synthetic',client=client,concurrency=1)
            write_bundle(bundle,args.output/f'{case}.json')
            result={'case_id':case,'facts':len(bundle.facts),'status':bundle.manifest.status,'gaps':len(bundle.processing_gaps)}
            cases.append(result)
            print(json.dumps(result),flush=True)
    finally:
        client.close()
        args.output.mkdir(parents=True,exist_ok=True)
        metrics={'model':client.model,'max_calls':args.max_calls,'usage':client.usage.snapshot(),
            'cache_hits':client.cache_hits,'elapsed_seconds':round(time.perf_counter()-started,2),'cases':cases}
        (args.output/'run-metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
