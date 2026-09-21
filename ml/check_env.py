import sys

import joblib
import matplotlib
import numpy
import pandas
import pyarrow
import sklearn


def main() -> None:
    print("ASTRA ML environment")
    print("=" * 40)

    print("Python:", sys.version.split()[0])
    print("Executable:", sys.executable)

    print()
    print("Packages:")

    print("numpy:", numpy.__version__)
    print("pandas:", pandas.__version__)
    print("scikit-learn:", sklearn.__version__)
    print("joblib:", joblib.__version__)
    print("matplotlib:", matplotlib.__version__)
    print("pyarrow:", pyarrow.__version__)

    print()
    print("Environment check: OK")


if __name__ == "__main__":
    main()
