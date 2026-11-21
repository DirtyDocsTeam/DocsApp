plugins {
    kotlin("jvm") version "2.4.10"
    kotlin("plugin.allopen") version "2.4.10"
    kotlin("plugin.serialization") version "2.4.10"
    id("io.quarkus")
    id("nu.studer.jooq") version "10.1.1"
}

repositories {
    mavenCentral()
    mavenLocal()
}

val quarkusPlatformGroupId: String by project
val quarkusPlatformArtifactId: String by project
val quarkusPlatformVersion: String by project

dependencies {
    implementation(enforcedPlatform("${quarkusPlatformGroupId}:${quarkusPlatformArtifactId}:${quarkusPlatformVersion}"))
    implementation("io.quarkus:quarkus-info")
    implementation("io.quarkus:quarkus-config-yaml")
    implementation("io.quarkus:quarkus-smallrye-health")
    implementation("io.quarkus:quarkus-jdbc-postgresql")
    implementation("io.quarkus:quarkus-micrometer")
    implementation("io.quarkus:quarkus-micrometer-registry-prometheus")
    implementation("io.quarkus:quarkus-quartz")
    implementation("io.quarkus:quarkus-oidc")
    implementation("io.quarkus:quarkus-mailer")
    implementation("io.quarkus:quarkus-liquibase")
    implementation("org.mindrot:jbcrypt:0.4")
    implementation("io.quarkiverse.quinoa:quarkus-quinoa:2.9.2")
    implementation("org.citrusframework:citrus-quarkus:5.0.2")
    testImplementation("io.quarkus:quarkus-junit5-mockito")

    implementation("io.quarkus:quarkus-grpc")
    implementation("io.quarkus:quarkus-rest")
    implementation("io.quarkiverse.jooq:quarkus-jooq:2.2.0")
    implementation("io.quarkus:quarkus-kotlin")
    implementation("io.quarkus:quarkus-smallrye-graphql")
    implementation("io.quarkus:quarkus-rest-kotlin-serialization")
    implementation("org.jetbrains.kotlin:kotlin-stdlib-jdk8")
    implementation("io.quarkus:quarkus-arc")
    testImplementation("io.quarkus:quarkus-junit")
    testImplementation("io.rest-assured:rest-assured")

    jooqGenerator("org.postgresql:postgresql:42.7.14")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
}

group = "ru.dirtydocs"
version = "1.0"

java {
    sourceCompatibility = JavaVersion.VERSION_21
    targetCompatibility = JavaVersion.VERSION_21
}

allOpen {
    annotation("jakarta.ws.rs.Path")
    annotation("jakarta.enterprise.context.ApplicationScoped")
    annotation("jakarta.persistence.Entity")
    annotation("io.quarkus.test.junit.QuarkusTest")
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_21
        javaParameters = true
    }
}

jooq {
    version.set("3.20.5")

    configurations {
        create("main") {
            generateSchemaSourceOnCompilation.set(false)

            jooqConfiguration.apply {
                jdbc.apply {
                    driver = "org.postgresql.Driver"

                    url = System.getenv("DB_URL")
                        ?: "jdbc:postgresql://localhost:5432/dirtydocs"

                    user = System.getenv("DB_USER")
                        ?: "postgres"

                    password = System.getenv("DB_PASSWORD")
                        ?: "postgres"
                }

                generator.apply {
                    name = "org.jooq.codegen.KotlinGenerator"

                    database.apply {
                        name = "org.jooq.meta.postgres.PostgresDatabase"
                        inputSchema = "public"
                        includes = ".*"
                        excludes = "databasechangelog|databasechangeloglock"
                    }

                    target.apply {
                        packageName = "ru.dirtydocs.api.generated.jooq"
                        directory = "build/generated-src/jooq/main"
                    }
                }
            }
        }
    }
}
