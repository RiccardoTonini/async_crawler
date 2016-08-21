###########  A Web crawler using asyncio coroutines ##############

This program is based on python asyncio library and requires python 3.

After implementing a crawler which was processing urls in a serial way,
I decided to adopt an approach that would allow multiple urls to be fetched
at the same time.

This crawler is based on the following tutorial:

http://aosabook.org/en/500L/a-web-crawler-with-asyncio-coroutines.html

- Create a local virtual environment. Change path/to/python3 so that it points to your python3 interpreter.

	virtualenv --python=path/to/python3 env/

- Install requirements:

	env/bin/pip install -r requirements.txt

- Run as:

  	env/bin/python3 main.py --target='www.bbc.co.uk' --max_redirect=10 --max_tasks=10


--target defaults to 'http://www.bbc.co.uk/' if omitted
--max_redirect defaults to 10 if omitted
--max_tasks defaults to 10 if omitted
