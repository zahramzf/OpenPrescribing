# OpenPrescribing CLI Tool
A command-line tool that looks up the chemical substance for a full 15-character
BNF code, then prints the Integrated Care Board (ICB) that prescribed it most in
each of the last five years, one line per month. An optional `--weighted` mode
ranks ICBs by items prescribed per registered patient instead of raw item count.

Data is retrieved live from the [OpenPrescribing API](https://openprescribing.net/api/).

## Requirements

- [Docker](https://docs.docker.com/get-docker/) (no local Python installation needed)

## Installation and running

The project is packaged as a Docker image so it can be run without installing
Python or any dependencies on your machine.

**1. Build the image** (run once, from the project root):

```bash
docker build -t optool .
```

**2. Run the tool** against a BNF code:

```bash
docker run --rm optool 1304000H0AAAAAA
```

**3. Run in weighted mode** (ranks ICBs by items per registered patient):

```bash
docker run --rm optool --weighted 1304000H0AAAAAA
```

# Running the tests

Tests run against mocked API responses:

```bash
python -m unittest discover -s tests
```

## Design decisions

* **Validation first.** Checks the BNF code is 15 characters before making any request.
* **Chemical code.** Uses the first 9 characters of the BNF code.
* **User agent.** Sends the required OpenPrescribing user agent.
* **Tie-breaking.** Keeps the first API result when values are equal.
* **Weighted mode.** Uses `total_list_size` to rank items per patient.
* **Strict errors.** Fails if list size is missing or invalid.
* **`Decimal` math.** Avoids floating-point rounding issues.
* **Retries.** Retries transient HTTP errors with backoff.
* **Testable design.** Uses an injectable request function for tests.

## How AI was used
I used AI as an assistant to help with initial ideas for the structure of the program, suggested ways to organise the code and helped me draft parts of the implementation and tests. I then reviewed, edited and ran the code myself and made changes where needed to make sure it worked correctly and matched the specification.

Used it as a support tool for drafting, debugging, and improving the clarity of the code and README.
