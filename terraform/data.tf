data "archive_file" "lambda_dummy" {
  type        = "zip"
  output_path = "${path.module}/.terraform/dummy_lambda.zip"

  source {
    content  = <<-EOF
      import json

      def handler(event, context):
          return {
              "statusCode": 200,
              "headers": {"Content-Type": "application/json"},
              "body": json.dumps({
                  "status": "placeholder",
                  "message": "Infraestructura lista. Esperando despliegue de la app."
              })
          }
    EOF
    filename = "lambda_function.py"
  }
}