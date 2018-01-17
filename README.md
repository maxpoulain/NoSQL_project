# NoSQL_project

## Architecture

![architecture](https://github.com/maxpoulain/NoSQL_project/blob/master/architecture.png)


## Preprocess data

[Zeppelin Notebook](https://github.com/maxpoulain/NoSQL_project/blob/master/Projet_NoSQL_preprocess1.json)

### Import packages
```
import org.apache.spark.input.PortableDataStream
import java.util.zip.ZipInputStream
import java.io.BufferedReader
import java.io.InputStreamReader
```

### Configuration of aws credentials
```
sc.hadoopConfiguration.set("fs.s3a.access.key", "*****") sc.hadoopConfiguration.set("fs.s3a.secret.key", "*****")
sc.hadoopConfiguration.setInt("fs.s3a.connection.maximum", 10000)
```
### Import data from S3 Telecom

#### Import event data into RDD
```
val eventRDD = sc.binaryFiles("s3a://telecom.gdelt/20171[0-9]*.export.CSV.zip")
.flatMap{case (name: String, content: PortableDataStream) => val zis = new ZipInputStream(content.open)
Stream.continually(zis.getNextEntry)
.takeWhile(_ != null)             
.flatMap { _ => val br = new BufferedReader(new InputStreamReader(zis))
Stream.continually(br.readLine()).takeWhile(_ != null)
}}
eventRDD.count()
```

#### Transform RDD to DataFrame
```
val evtest = eventRDD.map(x => x.split("\t")).map(row => row.mkString(";")).map(x => x.split(";")).toDF()
val events = evtest.withColumn("_tmp", $"value").select($"_tmp".getItem(0).as("GlobalEventID"),$"_tmp".getItem(1).as("Date"),$"_tmp".getItem(27).as("EBC"),$"_tmp".getItem(51).as("TypeGeo"),$"_tmp".getItem(52).as("Geo"),$"_tmp".getItem(58).as("ActionGeo"))
events.count()
```

#### Import mentions data into RDD
```
val mentionsRDD = sc.binaryFiles("s3a://telecom.gdelt/20171[0-9]*.mentions.CSV.zip")
.flatMap{
    case (name: String, content: PortableDataStream) =>
    val zis = new ZipInputStream(content.open)
    Stream.continually(zis.getNextEntry)
    .takeWhile(_ != null)
    .flatMap { _ =>
        val br = new BufferedReader(new InputStreamReader(zis))
        Stream.continually(br.readLine()).takeWhile(_ != null)
      }
  }
mentionsRDD.count()
```

#### Transform RDD to DataFrame
```
val mentest = mentionsRDD.map(x => x.split("\t")).map(row => row.mkString(";")).map(x => x.split(";")).toDF()
val mentions = mentest.withColumn("_tmp", $"value").select($"_tmp".getItem(0).as("GlobalEventID"),$"_tmp".getItem(2).as("MentionTimeDate"),$"_tmp".getItem(3).as("MentionType"),$"_tmp".getItem(4).as("MentionSourceName"))
mentions.count()
```

#### Clean mentions df
```
val clean_mentions = mentions.filter($"MentionType" === 1)
clean_mentions.show(5)

```

#### Import domainCountry data from hdfs
```
val domain = spark.read
     .format("csv")
     .option("header", "true")
     .load("hdfs:///user/hadoop/domainCountry")
val clean_domain = domain.withColumnRenamed("Domain", "MentionSourceName")
clean_domain.show()
```

#### Join clean_mentions and clean_domain
```
val df_mentions = clean_mentions.join(clean_domain,"MentionSourceName")
df_mentions.show(5)
```

#### Join df_mentions with df
```
val df_final = df_mentions.join(events,"GlobalEventID")
df_final.show()
```

#### Insert data into S3 bucket to have backup
```
df_final.write.parquet("s3a://gdelt.project-fpss-backup/prepared_dataset")
```


## Cassandra Installation and Configuration


### Stop cassandra
```
sudo service cassandra stop
```

### Open ports on aws
- 61621
- 8888
- 7199
- 7001
- 61620
- 9160
- 7000
- 9042
- 22

### Edit cassandra.yaml on each node
```
sudo vi /etc/cassandra/cassandra.yaml
```
- cluster_name => gdelt
- seeds => private ip
- listen_address => private ip
- rpc_address => private ip
- endpoint_snitch => Ec2Snitch

### Delete older files and Start Cassandra
```
sudo rm -rf /var/lib/cassandra/data/system/*
sudo rm /etc/cassandra/cassandra-topology.properties
sudo service cassandra start
```


## Cassandra Preprocess and Insertion

### Creation of Cassandra keyspace and table
```
CREATE KEYSPACE gdelt
       WITH replication = {
           'class' : 'SimpleStrategy',
           'replication_factor' : 3
       };
```
```
CREATE TABLE gdelt.mentions_by_location_eventcode (
           location text,
           eventcode int,
           day text,
           country text,
           frequency int,
           PRIMARY KEY (( location, eventcode ), day, country)
     );

```

### Schema of the data in Cassandra

![dataincassandra](https://github.com/maxpoulain/NoSQL_project/blob/master/dataincassandra.png)

### Start spark-shell with cassandra connector and cassandra host
```
spark-shell --packages com.datastax.spark:spark-cassandra-connector_2.11:2.0.1 --conf spark.cassandra.connection.host=ec2-35-170-17-129.compute-1.amazonaws.com
```

### Define S3 credentials
```
sc.hadoopConfiguration.set("fs.s3a.access.key", "*****")
sc.hadoopConfiguration.set("fs.s3a.secret.key", "*****")
sc.hadoopConfiguration.setInt("fs.s3a.connection.maximum", 1000000)
```

### Read parquet from S3 bucket
```
val df = spark.read.parquet("s3a://gdelt.project-fpss-backup/prepared_dataset")
```

### Preprocess data
```
val df2 = df.filter($"EBC" === "180" || $"EBC" === "183").withColumn("Geo", split($"Geo", "\\,").getItem(0)).withColumn("MentionTimeDate", $"MentionTimeDate".substr(1,9)).groupBy($"Geo", $"EBC", $"MentionTimeDate", $"FIPSCountryCode").agg(count(lit(1)).alias("Freq"))
```
```
val newnames = Seq("location", "eventcode", "day", "country", "frequency")
val dfRenamed = df2.toDF(newnames: _*)
dfRenamed.show()
```

|          location|eventcode|      day|country|frequency|
|------------------|---------|---------|-------|---------|
|            Boston|      180|201711031|     US|        7|
|            Mumbai|      180|201712050|     IN|        6|
|          Columbus|      180|201710021|     US|       28|
|         Las Vegas|      183|201710080|     US|        7|
|          Pretoria|      180|201710090|     US|        2|
|           Toronto|      180|201711141|     CA|        3|
|      Lakki Marwat|      180|201711271|     PK|        3|
|           Abilene|      180|201711292|     US|        5|
|    Allegan County|      180|201712041|     US|        1|
|        California|      180|201712142|     US|      109|
| Montgomery County|      180|201710130|     US|        1|
|           Florida|      180|201711011|     US|       10|
|Middlebury College|      180|201711100|     US|        4|
|            Kansas|      180|201711110|     US|       12|
|            London|      180|201711280|     US|        8|
|              Cuba|      180|201710162|     US|        1|
|             Cairo|      180|201711250|     MY|        6|
|           Alabama|      180|201712061|     US|       76|
|        New Mexico|      180|201712121|     RS|        2|
|          Dagestan|      180|201710031|     FR|        3|

### Import package for insertion in Cassandra DataBase
```
import org.apache.spark.sql.cassandra._
import com.datastax.spark.connector._
```

### Insert Data
```
dfRenamed.write.format("org.apache.spark.sql.cassandra").mode("overwrite").options(Map("table" -> "mentions_by_location_eventcode", "keyspace" -> "gdelt")).save()
```

### Test Cassandra
- Connect to one of the nodes (ssh)
- ``` cqlsh ip of the node ```
- ``` USE gdelt; ```
- ``` SELECT * FROM mentions_by_location_eventcode LIMIT 10; ```
