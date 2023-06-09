
from WebCrawler import WebCrawler
import pickle
import sys
import argparse
import numpy as np
import random
from sklearn.metrics.pairwise import euclidean_distances
from nltk.stem import PorterStemmer
import math
import csv
from textwrap import wrap


class SearchEngine(WebCrawler):
    def __init__(self, seed_url):
        super().__init__(seed_url)
        self.thesaurus = None  # {word: alternative}
        self.thesaurus_file = None
        self.clusters = None  # {leader: [ (followerN, distanceN) ]}
        self.N = None  # number of docs indexed
        self.df = None  # doc frequency for each term

    # parses a thesaurus file and sets attribute
    def set_thesaurus(self, thesaurus_file):
        thesaurus = {}

        try:
            with open(thesaurus_file) as csvfile:
                reader = csv.reader(csvfile, delimiter=',')
                for row in reader:
                    word = row[0]
                    alternatives = row[1:]
                    thesaurus[word] = alternatives

            self.thesaurus = thesaurus
            self.thesaurus_file = thesaurus_file

        except IOError as e:
            print("Error opening" + thesaurus_file + " error({0}): {1}".format(e.errno, e.strerror))
        except ValueError:
            print("Error opening" + thesaurus_file + ": Data is not correctly formatted. See README.")
        except:
            print("Error opening" + thesaurus_file + "Unexpected error:", sys.exc_info()[0])
            raise

    # loads index from disk
    def load_index(self, filename="Output/exported_index.obj"):
        try:
            f = open(filename, "rb")
        except IOError:
            print("Error opening index file: " + filename)
            return 0

        tmp_dict = pickle.load(f)
        f.close()

        self.__dict__.update(tmp_dict)
        print("Index successfully imported from disk.")

    # saves index from disk
    def save_index(self, filename="Output/exported_index.obj"):
        f = open(filename, 'wb')
        pickle.dump(self.__dict__, f)
        f.close()

    def validate_query(self, query):
        for q in query.split():
            if self.word_is_valid(q) is not True:
                return False
        return True

    """
    clusters tf matrix into k pairs of leaders and followers
    populates self.clusters
    """
    def cluster_docs(self, k=5):
        # transpose tf matrix
        X = np.matrix([list(x) for x in zip(*self.frequency_matrix)])

        # normalize term frequencies
        X_max, X_min = X.max(), X.min()
        X = (X - X_min) / (X_max - X_min)

        if len(X) < k:
            print("Warning: not enough documents to pick " + str(k) + " leaders.")
            k = int(len(X) / 2)
            print("Clustering around " + str(k) + " leaders.")

        # pick a random sample of k docs to be leaders
        leader_indices = random.sample(range(0, len(X)), k)
        follower_indices = list(set([i for i in range(len(X))]) - set(leader_indices))

        # stores leader: [(follower, distance)]
        clusters = {l: [] for l in leader_indices}

        # assign each follower to its closest leader
        for f in follower_indices:
            min_dist = sys.maxsize
            min_dist_index = -1

            for l in leader_indices:
                cur_dist = euclidean_distances(X[f], X[l])
                if cur_dist < min_dist:
                    min_dist = cur_dist
                    min_dist_index = l

            clusters[min_dist_index].append((f, min_dist[0][0]))

        self.clusters = clusters

    # returns a normalized list
    def normalize_list(self, input_list):
        # compute the square root of the sum of squares in the list (norm of list)
        l_norm = math.sqrt(sum([l**2 for l in input_list]))

        # normalize list by dividing each element by the norm of list
        if l_norm > 0:
            input_list = [l/l_norm for l in input_list]
        return input_list

    # modify parent method to keep track of number of docs and doc freq for each term
    def build_frequency_matrix(self):
        super().build_frequency_matrix()

        self.N = len(self.frequency_matrix[0])
        self.df = [sum(row) for row in self.frequency_matrix]

    # returns log weighted tf-idf weight of a document or query (log tf times idf)
    def tf_idf(self, doc):
        w = []

        for d in range(len(doc)):
            if doc[d] > 0:
                w.append((1 + math.log10(doc[d])) * math.log10(self.N / self.df[d]))
            else:
                w.append(0)

        return w

    # returns cos sim between query and document
    def cosine_similarity(self, query, doc):
        # compute tf-idf for query and doc
        q_prime = self.tf_idf(query)
        d_prime = self.tf_idf(doc)

        # normalize query and doc
        q_prime = self.normalize_list(q_prime)
        d_prime = self.normalize_list(d_prime)

        # return dot product
        return sum([q_prime[i] * d_prime[i] for i in range(len(q_prime))])

    """
    compares a valid user query to each document and returns a list of results
    
    return type is a 2D list: [[DocId, title, first 20 words]]
    
    Arguments: k is the number of results to return
               query_expanded is a boolean used to stop the recursive call for query expansion 
    """
    def process_query(self, user_query, k=6, query_expanded=False):
        # list of scores for each query vs docs
        scores = {doc_id: 0 for doc_id in self.doc_titles.keys()}  # DocID : score

        # set score equal to .25 if any of the query terms appear in the titles
        for t in self.doc_titles.keys():
            cur_title = self.doc_titles[t].lower()
            if len(set(user_query.split()).intersection(cur_title.split())) > 0:
                scores[t] = 0.25

        # split query into list
        query = user_query
        query = query.split()

        # remove stop words
        query = [q for q in query if q not in self.stop_words]

        # stem terms in query
        stemmer = PorterStemmer()
        query = [stemmer.stem(q) for q in query]

        # filter out terms that aren't in any of the documents
        query = [q for q in query if q in self.all_terms]

        # convert query to list of term frequencies
        query = [query.count(term) for term in self.all_terms]

        # transpose tf matrix to get list of docs
        docs = [list(x) for x in zip(*self.frequency_matrix)]

        # execute cosine similarity for each document, add to the score
        for i, (doc_id, score) in enumerate(scores.items()):
            scores[doc_id] += self.cosine_similarity(query, docs[i])

        # sort by scores in descending order
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # populate 2D list sorted results: [[score, title, URL, first 20 words]], but only keep results if score > 0
        results = [['%06.4f' % score, self.doc_titles[doc_id], self.doc_urls[doc_id].replace(self.domain_url, ''),
                    " ".join(self.doc_words[doc_id][:20])] for doc_id, score in sorted_scores if score > 0]

        # Handle K, < K, and K/2 results
        # if less results than threshold, do thesaurus expansion
        if len(results) < k/2 and query_expanded is False:
            print("Less than K/2 results. Performing thesaurus expansion...")

            # split original query into list
            query = user_query.split()

            # expand query using the thesaurus
            for term in query:
                # add synonyms to the end of the query
                if term in self.thesaurus:
                    query += [syn for syn in self.thesaurus[term] if syn not in query]

            # recursively call process_query with the new query
            return self.process_query(" ".join(query), k, True)

        # return the first k results
        return results[:k]

    def display_clusters(self):
        if self.clusters is not None:
            for leader, followers in self.clusters.items():
                print("Doc" + str(leader) + ":", end="")

                if len(followers) is 0:
                    print("\tNo followers", end="")
                print()

                for follower in followers:
                    print("\t\t+ Doc" + str(follower[0]) + " (Distance: " + str(follower[1]) + ")")
                print()
        else:
            print("Documents not yet clustered.")

    def show_main_menu(self):
        self.print_divider()
        print("|    IIITD Search Engine                                            |\n"
              "|                                                                    |\n"
              "|    [0] Exit                                                        |\n"
              "|    [1] Build Index                                                 |\n"
              "|    [2] Search Documents                                            |")
        self.print_divider()

    def print_divider(self):
        [print("-", end="") for x in range(70)]
        print()

    def display_menu(self):
        run_program = True  # flag for continuing program

        while run_program:
            self.show_main_menu()

            # prompt user for initial menu selection
            main_menu_input = "-1"
            while main_menu_input.isdigit() is False or int(main_menu_input) not in range(0, 3):
                main_menu_input = input("Please select an option: ")
            self.print_divider()

            # user wants to build index (crawl)
            if int(main_menu_input) == 1:
                # check to make sure index hasn't been built
                if self.clusters is not None:
                    print("Index has already been built. \nYou'll need to restart the program to build a new one.")

                else:  # prompt user to import from file
                    import_input = "-1"
                    while import_input != "y" and import_input != "n":
                        import_input = input("Would you like to import the index from disk? (y/n) ").lower()

                    # import the index from file
                    if import_input == "y":
                        self.load_index()

                    # crawl site to build index
                    else:
                        # print info about user choices
                        print("\nSeed URL: " + self.seed_url)
                        print("Page limit: " + str(self.page_limit))
                        print("Stop words: " + str(self.stop_words_file))
                        print("Thesaurus: " + str(self.thesaurus_file))

                        # build index
                        print("\nBeginning crawling...\n")
                        search_engine.crawl()
                        print("\nIndex built.")
                        self.print_divider()

                        # ask user if they want to see optional output
                        info_input = "-1"
                        while info_input != "y" and info_input != "n":
                            info_input = input("Would you like to see info about the pages crawled? (y/n) ").lower()

                        # show user crawler duplicates, broken urls, etc
                        if info_input == "y":
                            search_engine.produce_duplicates()
                            print(search_engine)

                        # build tf matrix to be used for clustering
                        self.print_divider()
                        print("Building Term Frequency matrix...", end="")
                        sys.stdout.flush()

                        search_engine.build_frequency_matrix()
                        print(" Done.")

                        # export frequency matrix to file
                        f = open("Output/tf_matrix.csv", "w")
                        f.write(search_engine.print_frequency_matrix())
                        f.close()
                        print("\n\nComplete frequency matrix has been exported to Output/tf_matrix.csv")
                        self.print_divider()

                        # ask user if they want to see tf matrix
                        tf_input = "-1"
                        while tf_input != "y" and tf_input != "n":
                            tf_input = input("\nWould you like to see the most frequent terms? (y/n) ").lower()

                        # show user tf matrix
                        if tf_input == "y":
                            self.print_divider()
                            print("Most Common Stemmed Terms:\n")
                            print("{: <15} {: >25} {: >25}".format("Term", "Term Frequency", "Document Frequency"))
                            print("{: <15} {: >25} {: >25}".format("----", "--------------", "------------------"))
                            count = 1
                            for i, j, k in search_engine.n_most_common(20):
                                print("{: <15} {: >25} {: >25}".format((str(count) + ". " + i), j, k))
                                count += 1

                        self.print_divider()

                        print("\nBeginning clustering...")
                        # cluster docs
                        self.cluster_docs()

                        # ask user if they want to see clustering
                        c_input = "-1"
                        while c_input != "y" and c_input != "n":
                            c_input = input("\nDocuments clustered. Would you like to see their clustering? (y/n) ").lower()

                        # show clustering
                        if c_input == "y":
                            self.print_divider()
                            self.display_clusters()

                        b_input = "-1"
                        while b_input != "y" and b_input != "n":
                            b_input = input("\nWould you like to export this index to disk? (y/n) ").lower()

                        if b_input == "y":
                            self.save_index()
                            print("Exported to Output/exported_index.obj.")

            # user wants to enter search query
            elif int(main_menu_input) == 2:
                if len(self.visited_urls) == 0:
                    print("You must build the index first.")
                else:
                    while True:
                        # prompt user to enter query
                        query_input = input("\nPlease enter a query or \"stop\": ")

                        # query is valid
                        if self.validate_query(query_input):
                            # stop program if user enters "stop"
                            if "stop" in query_input:
                                run_program = False
                                break

                            # process the query for searching
                            else:
                                results = self.process_query(query_input)
                                self.print_divider()

                                # display results
                                if len(results) > 0:
                                    for i in range(len(results)):
                                        print(str(i+1) + ".\t[" + str(results[i][0]) + "]  " + results[i][1] + " (" + results[i][2] + ")")
                                        print()
                                        print("\t\"" + "\n\t ".join(wrap(results[i][3], 50)) + "\"")
                                        print("\n")
                                else:
                                    print("No results found.")
                                self.print_divider()

                        else:
                            print("Invalid query.")
            else:
                break

        print("\nGoodbye!")


if __name__ == "__main__":
    search_engine = SearchEngine("http://techtree.iiitd.edu.in/viewDescription/filename?=CSE121")

    # handle command line arguments
    parser = argparse.ArgumentParser(description="Search Engine IIITD")
    parser.add_argument("-p", "--pagelimit", help="Maximum number of pages to crawl. (Required)", required=False, default="60")
    parser.add_argument("-s", "--stopwords",
                        help="Stop words file: a newline separated list of stop words. (Default is Input/stopwords.txt)", required=False, default="Input/stopwords.txt")
    parser.add_argument("-t", "--thesaurus",
                        help="Thesaurus file: a comma separated list of words and their synonyms. (Default is Input/thesaurus.csv)", required=False, default="Input/thesaurus.csv")

    argument = parser.parse_args()

    # set attributes based off arguments
    if int(argument.pagelimit) > 1:
        search_engine.set_page_limit(argument.pagelimit)

        if argument.stopwords:
            search_engine.set_stop_words(argument.stopwords)
        if argument.thesaurus:
            search_engine.set_thesaurus(argument.thesaurus)

        # show main menu to user
        search_engine.display_menu()
    else:
        print("Sorry. You must crawl a minimum of 2 pages. Otherwise, why would you need a search engine?")
