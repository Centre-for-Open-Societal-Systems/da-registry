// One multibranch job; pull requests always use validation-only dev behavior.
def delivery
node {
    checkout scm
    def environment = env.BRANCH_NAME == 'staging' && !env.CHANGE_ID ? 'staging' : 'dev'
    delivery = load("ci/pipelines/${environment}.groovy")
}
delivery.call()
