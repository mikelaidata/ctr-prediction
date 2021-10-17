from pyspark.sql import SparkSession
import pyspark.sql.functions as F
from pyspark.ml.feature import StringIndexer, VectorAssembler, OneHotEncoder
from pyspark.ml import Pipeline

spark = SparkSession.builder \
                    .appName("ctr prediction") \
                    .getOrCreate()

impression = spark.read.option('header', 'true') \
                       .option('inferSchema', 'true') \
                       .csv('gs://pyspark-yli/avazu-ctr-prediction/train.csv') \
                       .selectExpr("*", "substr(hour, 7) as hr") \

strCols = map(lambda t: t[0], filter(
    lambda t: t[1] == 'string', impression.dtypes))
intCols = map(lambda t: t[0], filter(
    lambda t: t[1] == 'int', impression.dtypes))

# [row_idx][json_idx]
strColsCount = list(sorted(map(lambda c: (c, impression.select(F.countDistinct(
    c)).collect()[0][0]), strCols), key=lambda x: x[1], reverse=True))
intColsCount = list(sorted(map(lambda c: (c, impression.select(F.countDistinct(
    c)).collect()[0][0]), intCols), key=lambda x: x[1], reverse=True))

# All of the columns (string or integer) are categorical columns
#  except for the [click] column
maxBins = 70
categorical = list(map(lambda c: c[0],
                       filter(lambda c: c[1] <= maxBins, strColsCount)))
categorical += list(map(lambda c: c[0],
                   filter(lambda c: c[1] <= maxBins, intColsCount)))
categorical.remove('click')

# Apply string indexer to all of the categorical columns
#  And add _idx to the column name to indicate the index of the categorical value
stringIndexers = list(map(lambda c: StringIndexer(
    inputCol=c, outputCol=c + "_idx"), categorical))

# Apply one hot encoding
oneHotEncoders = list(map(lambda c: OneHotEncoder(inputCol = c + "_idx", outputCol = c + "_onehot"), categorical))

# Assemble the put as the input to the VectorAssembler
#   with the output being our features
assemblerInputs = list(map(lambda c: c + "_onehot", categorical))
vectorAssembler = VectorAssembler(
    inputCols=assemblerInputs, outputCol="features"
)

# The [click] column is our label
labelStringIndexer = StringIndexer(inputCol="click", outputCol="label")

# The stages of our ML pipeline
stages = stringIndexers + oneHotEncoders + [vectorAssembler, labelStringIndexer]

# Create our pipeline
pipeline = Pipeline(stages=stages)

# create transformer to add features
featurizer = pipeline.fit(impression)

# dataframe with feature and intermediate transformation columns appended
featurizedImpressions = featurizer.transform(impression)

train, test = featurizedImpressions.select(["label", "features", "hr"]) \
                                   .randomSplit([0.7, 0.3], 42)

train.repartition(1) \
     .write \
     .mode('overwrite') \
     .parquet('gs://pyspark-yli/avazu-ctr-prediction/training.parquet')

test.repartition(1) \
    .write \
    .mode('overwrite') \
    .parquet('gs://pyspark-yli/avazu-ctr-prediction/validation.parquet')

spark.stop()
