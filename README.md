# Facerecognition YOLO

This repository hosts the Python application Facerecognition YOLO based on the
[YOLO Real-Time Object Detection](https://pjreddie.com/darknet/yolo/) project. This application is
packaged into a Docker container and executed on demand at
[AWS Lambda](https://aws.amazon.com/lambda/). On this page we document how to build the Docker image
and configure the AWS Lambda function which will execute the image.

- [Build The Docker image](#build-the-docker-image)
- [Create The AWS Lambda Function](#create-the-aws-lambda-function)
- [Links](#links)

## Build The Docker image

The Docker image uses the
[multi-stage approach](https://docs.docker.com/build/building/multi-stage/) in order to reduce the
size of the image and improve execution times. It uses
[official Python image](https://hub.docker.com/_/python/) as its base image and a
[distroless](https://github.com/GoogleContainerTools/distroless) Python image as its base for the
final stage of the image. The main logic of the app can be found in
[lambda_function.py](./lambda_function.py) (which was copied and re-factored from
[yolo_opencv.py](./yolo_opencv.py)).

```shell
docker build -t facerecognition-yolo:lambda -f ./Dockerfile.lambda --provenance=false .
```

**NOTE: the parameter `provenance=false` was added because Lambda does not support multi-platform
images, see
[this GitHub comment](https://github.com/docker/buildx/issues/1509#issuecomment-1378538197) for more
information.**

Tag and push the image to an ECR registry (Lambda only support ECR, not the Docker Hub or any other
registry), execute:

```shell
docker tag facerecognition-yolo:lambda 976682474571.dkr.ecr.eu-central-1.amazonaws.com/facerecognition-yolo:lambda
docker push 976682474571.dkr.ecr.eu-central-1.amazonaws.com/facerecognition-yolo:lambda
```

**NOTE: You may have to authenticate against the ECR repository before you can `pull` or `push`
images:**

```shell
aws ecr get-login-password --region eu-central-1 | docker login --username AWS --password-stdin 976682474571.dkr.ecr.eu-central-1.amazonaws.com
```

### Testing The Docker Image

See
[Test an image without adding RIE to the image](https://github.com/aws/aws-lambda-runtime-interface-emulator#test-an-image-without-adding-rie-to-the-image)
to learn how to debug or test the Docker image. In brief:

#### Install the AWS Lambda Runtime Interface Emulator

The following assumes an `arm64` based processor in your local system, i.e. MacBook M+ series:

```shell
mkdir -p ~/.aws-lambda-rie && curl -Lo ~/.aws-lambda-rie/aws-lambda-rie https://github.com/aws/aws-lambda-runtime-interface-emulator/releases/latest/download/aws-lambda-rie-arm64 && chmod +x ~/.aws-lambda-rie/aws-lambda-rie
```

#### Run A Test Docker Container

The following Docker container runs the RIE (see above) and uses a directory `tmp` as a volume so
that you can test with local files (NOTE: you'll have to update the code in
[lambda_function.py](./lambda_function.py) if you want to use non-S3 sources for the test image
files):

```shell
docker run --rm --name facerecognition-yolo -d -v `pwd`/tmp:/tmp -v ~/.aws-lambda-rie:/aws-lambda -p 9000:8080 --entrypoint /aws-lambda/aws-lambda-rie facerecognition-yolo:lambda /usr/local/bin/python -m awslambdaric lambda_function.lambda_handler
```

**NOTE: If you want to use S3 buckets (see below), you'll have to add the environment variables
`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` (or similar) to the command above. See
[here](https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html) for more
information.**

```shell
docker run ... --env AWS_ACCESS_KEY_ID=<value> --env AWS_SECRET_ACCESS_KEY=<value> ...
```

#### Create S3 Buckets

Create two S3 buckets (if you don't have any) to store source and resulting images:

```shell
aws s3 mb s3://a9s-aspekteins-input
aws s3 mb s3://a9s-aspekteins-output
```

Copy the source images to `s3://a9s-aspekteins-input` and use a URI to a blob as the `image`
parameter (see below).

#### Call the Lambda Function In The Test Docker Container

Use `cURL` to execute the Lambda function in your Test Docker container:

```shell
curl "http://localhost:9000/2015-03-31/functions/function/invocations" -d '{}'; echo # this should produce an error
```

```shell
curl "http://localhost:9000/2015-03-31/functions/function/invocations" -d '{"image": "s3://a9s-aspekteins-input/image.jpg", "filtered_image": "s3://a9s-aspekteins-output/image.jpg"}'; echo # if the Lambda function has access to both S3 buckets and the source image exists then the result should be stored in `s3://a9s-aspekteins-output/image.jpg`
```

## Create The AWS Lambda Function

First, we need a Role (and assoicated policies) that the AWS Lambda function can assume to obtain
acces both to ECR and the S3 buckets. First, create the policy that allows Lambda access to an ECR
repository where the Docker image is stored (you may want to update the `Resource` target in the
policy):

### IAM Policy And Role

```shell
aws iam create-policy --policy-name aspekteins-allow-access-ecr --policy-document file://aws-role-policydocument.json
```

and now create the role

```shell
export ROLE_NAME=aspekteins-lambda-facerecognition-yolo
aws iam create-role --role-name $ROLE_NAME --assume-role-policy-document file://aws-role.json
aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn arn:aws:iam::976682474571:policy/aspekteins-allow-access-ecr
aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess
aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

### S3 Buckets

Two S3 buckets are required (technically, one bucket with unique prefixes for source and resulting
image would be enough). Create these two buckets:

```shell
aws s3 mb s3://a9s-aspekteins-input
aws s3 mb s3://a9s-aspekteins-output
```

### Create The Lambda Function

```shell
export ACCOUNT_ID=$(aws sts get-caller-identity | jq -r ".Account")
aws lambda create-function --region eu-central-1 --function-name aspekteins-lambda-facerecognition-yolo --timeout 60 --role arn:aws:iam::${ACCOUNT_ID}:role/$ROLE_NAME --package-type Image --code ImageUri=976682474571.dkr.ecr.eu-central-1.amazonaws.com/facerecognition-yolo:lambda --memory-size 4096 --description "This Lambda function runs the YOLO Object Detection logic."
```

## Links

- [Dockerfile reference](https://docs.docker.com/reference/dockerfile/)
- [AWS Lambda: Building Lambda functions with Python](https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html)
- [AWS: Amazon S3 examples using SDK for Python (Boto3)](https://docs.aws.amazon.com/code-library/latest/ug/python_3_s3_code_examples.html)
- [Creating an up-to-date Distroless Python Image](https://alexos.dev/2022/07/08/creating-an-up-to-date-distroless-python-image/)
- [AWS Lambda function for OpenCV](https://github.com/iandow/opencv_aws_lambda)
